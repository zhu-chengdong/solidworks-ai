"""Native flat-assembly drawings with associated BOMs and per-instance balloons."""
from __future__ import annotations
import csv,hashlib,json,math,re,zipfile
from pathlib import Path
from .manufacturing import get,typed,views,evidence_view,write_json,digest
from .native_open import open_native_document
from .native_io import save_native_document
from .assembly_drawing_spec import AssemblyDrawingRequest,STAGES,validate_bom,validate_balloons

def leaf(component):return str(get(component,'Name2')).rsplit('/',1)[-1]

def source_documents(spec,out):
    documents=spec['source']['documents'];allowed=(out/'inputs'/'cad').resolve();files=[]
    if not 2<=len(documents)<=13:raise ValueError('A flat assembly with at most12 distinct parts is required')
    for item in documents:
        path=Path(item['path']).resolve()
        if not path.is_relative_to(allowed) or path.suffix.lower() not in {'.sldprt','.sldasm'} or digest(path)!=item['sha256']:
            raise ValueError('Only unchanged task-pinned assembly dependencies are allowed')
        files.append(path)
    if len({p.name.casefold() for p in files})!=len(files) or sum(p.suffix.lower()=='.sldasm' for p in files)!=1:
        raise ValueError('Ambiguous or nested assembly dependencies')
    assembly=Path(spec['source']['path']).resolve()
    if assembly not in files or assembly.suffix.lower()!='.sldasm':raise ValueError('Invalid pinned assembly')
    return assembly,files

def snapshot(assembly,models):
    from .native import _exact_bounds
    from integrations.czuryk.native_only import native_automation
    components=list(get(typed(assembly,'IAssemblyDoc'),'GetComponents',True) or [])
    if not 1<=len(components)<=24:raise ValueError('This drawing route accepts1-24 resolved top-level instances')
    result=[]
    for component in components:
        part=get(component,'GetModelDoc2');path=Path(get(component,'GetPathName')).resolve()
        if path.as_posix() not in models or part is None or int(get(part,'GetType'))!=1 or get(component,'GetChildren'):
            raise ValueError('Unresolved, nested or external assembly component')
        if str(get(component,'ReferencedConfiguration'))!=str(get(get(get(part,'ConfigurationManager'),'ActiveConfiguration'),'Name')):
            raise ValueError('Each part currently requires its active referenced configuration')
        if bool(get(component,'ExcludeFromBOM')):raise ValueError('Excluded BOM instances need separate qualification')
        bodies=list(get(part,'GetBodies2',0,False) or [])
        if not bodies:raise ValueError('Assembly component has no solid geometry')
        pose=list(get(get(component,'Transform2'),'ArrayData'))
        result.append({'name':leaf(component),'path':path.as_posix(),'source_name':models[path.as_posix()]['label'],
            'configuration':str(get(component,'ReferencedConfiguration')),'transform':pose,
            'bounds':_exact_bounds(bodies,pose),'body_count':len(bodies)})
    if len({r['name'] for r in result})!=len(result):raise ValueError('Ambiguous instance names')
    return sorted(result,key=lambda r:r['name'])

def check_snapshot(actual,expected):
    if len(actual)!=len(expected):raise RuntimeError('Assembly instance count changed')
    for a,b in zip(actual,expected):
        if any(a[k]!=b[k] for k in ('name','path','configuration','body_count','source_name')) or max(abs(x-y) for x,y in zip(a['transform'],b['transform']))>1e-8:
            raise RuntimeError('Assembly identity or component transform changed')
        for axis in ('min','max'):
            if max(abs(x-y) for x,y in zip(a['bounds'][axis],b['bounds'][axis]))>1e-5:raise RuntimeError('Assembly component geometry changed')

def drawing_document(app,record):
    from scripts.sw_assembly import _activate_model_document
    doc=open_native_document(app,record['drawing_path'],silent=True,raise_on_error=True)
    if int(get(doc,'GetType'))!=3:raise RuntimeError('Expected native drawing document')
    _activate_model_document(app,doc)
    return doc,typed(doc,'IDrawingDoc')

def prepare(app,out,spec,request,record,stamp):
    from scripts.sw_connect import new_document
    from solidworks_mcp.utils import find_solidworks
    original,files=source_documents(spec,out);folder=out/'models';folder.mkdir()
    assembly_path=folder/('assembly_'+stamp+'.SLDASM');assembly_path.write_bytes(original.read_bytes())
    dependencies=list(get(app,'GetDocumentDependencies2',str(assembly_path),False,False,False) or [])
    if len(dependencies)%2:raise ValueError('Invalid native dependency enumeration')
    names=[Path(p).name.casefold() for p in dependencies[1::2]]
    parts=[p for p in files if p.suffix.lower()=='.sldprt']
    if set(names)!={p.name.casefold() for p in parts} or len(names)!=len(set(names)):
        raise ValueError('ZIP dependencies differ from actual native assembly references')
    models={}
    for source in parts:
        if get(app,'GetDocumentDependencies2',str(source),False,False,False):raise ValueError('Leaf parts with external native references require separate qualification')
        copy=folder/(stamp+'_'+source.name);copy.write_bytes(source.read_bytes())
        old=next(p for p in dependencies[1::2] if Path(p).name.casefold()==source.name.casefold())
        if not app.ReplaceReferencedDocument(str(assembly_path),old,str(copy)):raise RuntimeError('Native assembly dependency replacement failed')
        label=re.sub(r'_[0-9a-f]{16}$','',source.stem)
        models[copy.resolve().as_posix()]={'source':source.name,'label':label}
    assembly=open_native_document(app,assembly_path,silent=True,raise_on_error=True)
    if int(get(assembly,'GetType'))!=2:raise ValueError('Source is not a native assembly')
    baseline=snapshot(assembly,models)
    native_components=list(get(typed(assembly,'IAssemblyDoc'),'GetComponents',True) or [])
    for path,data in models.items():
        part=get(next(c for c in native_components if Path(get(c,'GetPathName')).resolve().as_posix()==path),'GetModelDoc2')
        prop=get(get(part,'Extension'),'CustomPropertyManager','')
        get(prop,'Add3','SWAI_SourceDocument',30,data['label'],1)
    # Save the active task-owned assembly and references in one native call.
    # Opening a graphics window for every loaded child can exhaust commit.
    import pythoncom,win32com.client
    from solidworks_mcp.automation.com_utils import resolve_solidworks_constant as constant
    if Path(get(get(app,'ActiveDoc'),'GetPathName')).resolve()!=assembly_path.resolve():raise RuntimeError('The task assembly is not active')
    errors=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0);warnings=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    if not assembly.Save3(constant('swSaveAsOptions_Silent')|constant('swSaveAsOptions_SaveReferenced'),errors,warnings) or errors.value:
        raise RuntimeError('Native assembly/dependency save failed')
    if any(bool(get(get(c,'GetModelDoc2'),'GetSaveFlag')) for c in native_components):raise RuntimeError('A copied dependency was not saved')
    names=list(get(assembly,'GetModelViewNames') or [])
    keys={'isometric':{'*isometric','*等轴测'},'front':{'*front','*前视'},'top':{'*top','*上视'}}
    native_names={key:next((n for n in names if n.casefold() in allowed),None) for key,allowed in keys.items()}
    if not all(native_names.values()):raise ValueError('Native English/Chinese standard views could not be resolved')
    template=Path(__import__('os').environ.get('PROGRAMDATA','C:/ProgramData'))/'SOLIDWORKS/SOLIDWORKS 2024/templates/gb_a3.drwdot'
    doc=new_document(app,'drawing',template_path=str(template) if template.is_file() else None);drawing=typed(doc,'IDrawingDoc')
    sheet=get(drawing,'GetCurrentSheet');props=list(get(sheet,'GetProperties2'));sheet.SetProperties2(8,int(props[1]),1.,2.,True,.420,.297,True)
    drawing_path=out/('assembly_drawing_'+stamp+'.SLDDRW');save_native_document(app,doc,drawing_path)
    created={};scales={}
    for key,position in {'isometric':(.125,.185),'front':(.310,.190),'top':(.310,.115)}.items():
        view=drawing.CreateDrawViewFromModelView3(str(assembly_path),native_names[key],*position,0.)
        if view is None:raise RuntimeError('Native assembly drawing view insertion failed')
        view=typed(view,'IView');view.UseSheetScale=False;view.ScaleDecimal=1.;get(doc,'ForceRebuild3',False)
        box=list(get(view,'GetOutline'));width=box[2]-box[0];height=box[3]-box[1]
        maxw,maxh=(.120,.120) if key=='isometric' else (.120,.070)
        scale=request.scale if request.scale is not None else next((s for s in (1.,.5,.2,.1,.05) if width*s<=maxw and height*s<=maxh),None)
        if scale is None or width*scale>maxw or height*scale>maxh:raise ValueError('Requested assembly view scale does not fit A3')
        view.ScaleDecimal=scale;get(doc,'ForceRebuild3',False)
        row=evidence_view(view)
        expected=list(get(assembly,'GetStandardViewRotation',{'isometric':7,'front':1,'top':5}[key]))[:9]
        if max(abs(a-b) for a,b in zip(row['model_to_sheet'][:9],expected))>1e-6:raise RuntimeError('Native standard view rotation mismatch')
        created[key]=row;scales[key]=scale
    view_labels=[]
    drawing.ActivateView('')
    for key,label in {'isometric':'等轴测','front':'主视图','top':'俯视图'}.items():
        row=created[key];note=get(doc,'InsertNote',label)
        if note is None:raise RuntimeError('Native view label insertion failed')
        position=[row['position_m'][0],row['outline_m'][1]-.008,0.]
        if not get(note,'GetAnnotation').SetPosition2(*position):raise RuntimeError('Native view label placement failed')
        view_labels.append({'text':label,'position_m':position})
    title_notes=[]
    for note in get(get(drawing,'GetFirstView'),'GetNotes') or []:
        linked=str(get(note,'PropertyLinkedText'))
        unverified_mass='$PRP' in linked and any(word in linked.casefold() for word in ('mass','weight','质量','重量'))
        text=request.title if linked=='$PRPSHEET:"名称"' else ('ASM-'+stamp[:8] if linked=='$PRPSHEET:"代号"' else ('未核验' if unverified_mass else None))
        if text is not None:
            if not note.SetText(text):raise RuntimeError('Assembly drawing title field failed')
            title_notes.append(text)
    save_native_document(app,doc)
    executable=Path(find_solidworks());bom_templates=[executable.parent/'lang'/language/'bom-standard.sldbomtbt' for language in ('chinese-simplified','english')]
    bom_template=next((p for p in bom_templates if p.is_file()),None)
    if bom_template is None:raise ValueError('An installed native BOM template is required')
    record.update(drawing_path=str(drawing_path),assembly_path=str(assembly_path),models=models,components=baseline,
        model_hashes={str(p):digest(p) for p in folder.iterdir() if p.suffix.lower() in {'.sldprt','.sldasm'}},
        configuration=str(get(get(get(assembly,'ConfigurationManager'),'ActiveConfiguration'),'Name')),
        views=created,scales=scales,bom_template=str(bom_template),title_notes=title_notes,view_labels=view_labels)

def bom_objects(doc,record):
    feature=get(doc,'FeatureByName',record['bom_feature'])
    if feature is None:raise RuntimeError('Native BOM feature is missing')
    feature=typed(get(feature,'GetSpecificFeature2'),'IBomFeature')
    tables=list(get(feature,'GetTableAnnotations') or [])
    if len(tables)!=1 or int(get(feature,'TableType'))!=2:raise RuntimeError('Expected one native parts-only BOM')
    return typed(tables[0],'IBomTableAnnotation'),typed(tables[0],'ITableAnnotation')

def bom_evidence(doc,record):
    bom,table=bom_objects(doc,record);rows=[]
    if int(get(table,'ColumnCount'))!=3:raise RuntimeError('Unexpected native BOM columns')
    for index in range(1,int(get(table,'RowCount'))):
        cells=[str(get(table,'DisplayedText2',index,j,False)) for j in range(3)]
        components=list(get(bom,'GetComponents2',index,record['configuration']) or [])
        rows.append({'row':index,'item':cells[0],'label':cells[1],'quantity':int(cells[2]),'components':sorted(leaf(c) for c in components),'cells':cells})
    validate_bom(rows,record['components'])
    if [int(get(table,'GetColumnType',i)) for i in range(3)]!=[202,0,203] or str(get(bom,'GetColumnCustomProperty',1))!='SWAI_SourceDocument':
        raise RuntimeError('BOM column types or linked source-name property changed')
    for row in rows:
        expected=next(c['source_name'] for c in record['components'] if c['name']==row['components'][0])
        if row['label']!=expected:raise RuntimeError('Native BOM custom property identity differs from the source document')
    return {'rows':rows,'headers':[str(get(table,'DisplayedText2',0,j,False)) for j in range(3)],
        'position_m':list(get(get(table,'GetAnnotation'),'GetPosition')),
        'column_widths_m':[float(get(table,'GetColumnWidth',i)) for i in range(3)],
        'row_heights_m':[float(get(table,'GetRowHeight',i)) for i in range(int(get(table,'RowCount')))],
        'column_types':[int(get(table,'GetColumnType',i)) for i in range(3)],'native_type':int(get(table,'Type'))}

def insert_bom(app,out,record):
    doc,drawing=drawing_document(app,record)
    view=typed(next(v for v in views(drawing) if get(v,'GetName2')==record['views']['isometric']['name']),'IView')
    bom=view.InsertBomTable4(False,.245,.270,1,2,record['configuration'],record['bom_template'],False,0,False)
    if bom is None:raise RuntimeError('Native BOM insertion failed')
    bom=typed(bom,'IBomTableAnnotation');table=typed(bom,'ITableAnnotation')
    record['bom_feature']=str(get(get(get(bom,'BomFeature'),'GetFeature'),'Name'))
    if not table.DeleteColumn2(2,False):raise RuntimeError('Could not remove unused native description column')
    if table.SetColumnType3(1,204,False,'SWAI_SourceDocument')!=0 or not bom.SetColumnCustomProperty(1,'SWAI_SourceDocument'):
        raise RuntimeError('Native BOM custom-property column failed')
    for i,(title,width) in enumerate(zip(('序号','零件','数量'),(.014,.112,.014))):
        if not table.SetColumnTitle(i,title):raise RuntimeError('Native BOM column title failed')
        table.SetColumnWidth(i,width,0)
    for i in range(int(get(table,'RowCount'))):table.SetRowHeight(i,.006,0)
    get(doc,'ForceRebuild3',False);record['bom']=bom_evidence(doc,record);save_native_document(app,doc)

def balloon_evidence(drawing):
    import win32com.client
    result=[]
    for view in views(drawing):
        for value in get(view,'GetNotes') or []:
            note=typed(value,'INote')
            if not get(note,'IsBomBalloon'):continue
            annotation=get(note,'GetAnnotation');attached=list(get(annotation,'GetAttachedEntities3') or [])
            if len(attached)!=1:raise RuntimeError('Native balloon attachment is missing or ambiguous')
            component=get(typed(win32com.client.Dispatch(attached[0]),'IEntity'),'GetComponent')
            if component is None:raise RuntimeError('Native balloon is detached from its component')
            result.append({'name':str(get(note,'GetName')),'item':str(get(note,'GetBomBalloonText',True)),
                'component':leaf(component),'view':str(get(view,'GetName2')),'position_m':list(get(annotation,'GetPosition')),
                'leader_points_m':list(get(annotation,'GetLeaderPointsAtIndex',0)),
                'is_bom_balloon':bool(get(note,'IsBomBalloon')),'text_style':int(get(note,'GetBomBalloonTextStyle',True)),
                'upper_text_content':int(get(typed(get(note,'GetBalloonOptions'),'IBalloonOptions'),'UpperTextContent')),
                'attached_count':len(attached)})
    return sorted(result,key=lambda b:b['component'])

def check_balloon_evidence(actual,expected):
    if len(actual)!=len(expected):raise RuntimeError('Native balloon count changed after reopening')
    for a,b in zip(actual,expected):
        # SW regenerates the leader's start on the circle outline after font
        # layout. The annotation centre, BOM identity and attached tip must
        # persist. Check regenerated complete leaders separately for crossings.
        if {k:v for k,v in a.items() if k!='leader_points_m'}!={k:v for k,v in b.items() if k!='leader_points_m'}:
            raise RuntimeError('Native balloon position or association changed after reopening')
        p,q=a['leader_points_m'],b['leader_points_m']
        if len(p)!=6 or len(q)!=6 or not all(math.isfinite(v) for v in p+q) or math.dist(p[3:6],q[3:6])>1e-6:
            raise RuntimeError('Native balloon attachment tip changed after reopening')
    from .assembly_drawing_layout import crossing_count
    if crossing_count([(a['leader_points_m'][:2],a['leader_points_m'][3:5]) for a in actual]):
        raise RuntimeError('Native balloon leaders cross after reopening')

def insert_balloons(app,out,record):
    from .assembly_drawing_layout import arrange,crossing_count,project_component,select_tip
    doc,drawing=drawing_document(app,record)
    view=typed(next(v for v in views(drawing) if get(v,'GetName2')==record['views']['isometric']['name']),'IView')
    visible={leaf(c):c for c in get(view,'GetVisibleComponents') or []}
    if set(visible)!={c['name'] for c in record['components']}:raise ValueError('Every component must be visible in the isometric view for this drawing route')
    # Curve coordinates belong to the part, including repeated instances.
    # Compose its native transform with the drawing transform before choosing
    # a well-separated edge. Let SW keep a persistent native attachment;
    # SetLeaderAttachmentPointAtIndex can drift after reopen on SW2024.
    candidates=[];geometry={}
    matrix=list(get(get(view,'ModelToViewTransform'),'ArrayData'))
    for name,component in visible.items():
        edges=list(get(view,'GetVisibleEntities2',component,1) or [])
        if not edges:raise ValueError('Component has no visible native edge for a balloon')
        pose=next(c['transform'] for c in record['components'] if c['name']==name)
        curves=[]
        for edge in edges:
            params=list(get(edge,'GetCurveParams2'));curve=typed(get(edge,'GetCurve'),'ICurve')
            count=1 if get(curve,'IsLine') else 32
            samples=[list(get(curve,'Evaluate2',params[6]+(params[7]-params[6])*i/count,0))[:3] for i in range(count+1)]
            curves.append([project_component(point,pose,matrix) for point in samples])
        geometry[name]={'edges':edges,'curves':curves}
    for name,data in geometry.items():
        index,tip,clearance=select_tip(data['curves'],[line for other,row in geometry.items() if other!=name for line in row['curves']])
        candidates.append({'name':name,'edge':data['edges'][index],'tip':tip,'clearance_m':clearance,'y':tip[1]})
    candidates.sort(key=lambda r:r['y'],reverse=True)
    groups={True:[],False:[]}
    for index,c in enumerate(candidates):groups[index%2==0].append(c)
    native_notes={}
    for left,items in groups.items():
        for index,c in enumerate(items):
            doc.ClearSelection2(True);drawing.ActivateView(record['views']['isometric']['name'])
            selection=get(get(doc,'SelectionManager'),'CreateSelectData');selection.View=view
            if not typed(c['edge'],'IEntity').Select4(False,selection):raise RuntimeError('Native component edge selection failed')
            options=typed(get(doc.Extension,'CreateBalloonOptions'),'IBalloonOptions')
            options.Style=1;options.Size=2;options.UpperTextContent=1
            note=typed(doc.Extension,'IModelDocExtension').InsertBOMBalloon2(options)
            if note is None:raise RuntimeError('Native BOM balloon insertion failed')
            native_notes[c['name']]=note
            annotation=get(note,'GetAnnotation');x=.035 if left else .215;y=.255-index*.034
            if not annotation.SetPosition2(x,y,0.):raise RuntimeError('Native balloon placement failed')
    for attempt in range(3):
        tips={}
        for name,note in native_notes.items():
            annotation=typed(get(note,'GetAnnotation'),'IAnnotation');points=list(get(annotation,'GetLeaderPointsAtIndex',0) or [])
            if len(points)!=6:raise ValueError('This drawing route requires one straight native leader per balloon')
            tips[name]=points[3:5]
        positions=arrange(tips)
        for name,note in native_notes.items():
            if not get(note,'GetAnnotation').SetPosition2(*positions[name],0.):raise RuntimeError('Native balloon layout update failed')
        get(doc,'ForceRebuild3',False)
        segments=[]
        for note in native_notes.values():
            points=list(get(get(note,'GetAnnotation'),'GetLeaderPointsAtIndex',0));segments.append((points[:2],points[3:5]))
        if crossing_count(segments)==0:break
    else:raise ValueError('Native balloon leader crossings remain after bounded layout repair')
    record['balloon_layout']={'native_leader_crossings':0,'passes':attempt+1}
    record['balloon_layout']['selected_edge_samples']={c['name']:{'interior_point_m':c['tip'],'outline_clearance_m':c['clearance_m']} for c in candidates}
    record['balloons']=balloon_evidence(drawing)
    validate_balloons(record['balloons'],record['bom']['rows'],record['components']);save_native_document(app,doc)

def export_pdf(app,doc,drawing,path):
    import pythoncom,win32com.client
    export=typed(get(app,'GetExportFileData',1),'IExportPdfData');export.ViewPdfAfterSaving=False;export.ExportAs3D=False
    names=list(get(drawing,'GetSheetNames') or [])
    if len(names)!=1:raise ValueError('Assembly drawing export requires one explicit sheet')
    if not export.SetSheets(3,win32com.client.VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_BSTR,names)):raise RuntimeError('Native PDF sheet selection failed')
    errors=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0);warnings=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    if not doc.Extension.SaveAs(str(path),0,1,export,errors,warnings) or errors.value or not path.is_file():raise RuntimeError('Native assembly PDF export failed')

def deliver(app,out,record,stamp):
    from .assembly_drawing_pdf import inspect_pdf
    doc,drawing=drawing_document(app,record);save_native_document(app,doc);app.CloseDoc(str(get(doc,'GetTitle')))
    doc,drawing=drawing_document(app,record)
    actual={str(get(v,'GetName2')):evidence_view(v) for v in views(drawing)}
    for expected in record['views'].values():
        row=actual.get(expected['name'])
        if row is None or max(abs(a-b) for a,b in zip(row['model_to_sheet'],expected['model_to_sheet']))>1e-6:raise RuntimeError('Assembly drawing view changed after reopening')
    all_notes=[note for view in [get(drawing,'GetFirstView')]+views(drawing) for note in (get(view,'GetNotes') or [])]
    for expected in record.get('view_labels',[]):
        matched=[n for n in all_notes if str(get(n,'GetText'))==expected['text']]
        if not any(max(abs(a-b) for a,b in zip(list(get(get(n,'GetAnnotation'),'GetPosition'))[:2],expected['position_m'][:2]))<1e-5 for n in matched):
            raise RuntimeError('A native view label was lost or moved after reopening')
    assembly=open_native_document(app,record['assembly_path'],silent=True,raise_on_error=True)
    check_snapshot(snapshot(assembly,record['models']),record['components'])
    bom=bom_evidence(doc,record);balloons=balloon_evidence(drawing)
    if bom!=record['bom']:raise RuntimeError('Native BOM changed after reopening')
    from .assembly_drawing_layout import overlaps
    x,y=bom['position_m'][:2];bom_box=[x,y-sum(bom['row_heights_m']),x+sum(bom['column_widths_m']),y]
    if any(overlaps(bom_box,v['outline_m'],.002) for v in actual.values()):raise RuntimeError('Native BOM table overlaps a drawing view')
    validate_balloons(balloons,bom['rows'],record['components'])
    check_balloon_evidence(balloons,record['balloons'])
    for path,expected in record['model_hashes'].items():
        if digest(path)!=expected:raise RuntimeError('Copied assembly dependency bytes changed during drawing generation')
    pdf=out/('assembly_drawing_'+stamp+'.pdf');preview=out/'assembly-drawing-preview.png'
    export_pdf(app,doc,drawing,pdf);pdf_review=inspect_pdf(pdf,bom,balloons,preview,record.get('view_labels',[]))
    proof={'status':'passed','passed':True,'native_api_only':True,'solidworks_revision':str(get(app,'RevisionNumber')),
        'drawing':Path(record['drawing_path']).name,'pdf':pdf.name,'preview':preview.name,
        'save_reopen_verified':True,'source_model_preserved':True,'component_count':len(record['components']),
        'components':record['components'],'views':record['views'],'view_labels':record.get('view_labels',[]),'projection':'first_angle','bom':bom,'balloons':balloons,'balloon_layout':record['balloon_layout'],
        'pdf_review':pdf_review,'qualification_scope':'Single-sheet A3 flat resolved assembly, native parts-only BOM and one associated item-number balloon per instance; no exploded views, nested assemblies or manufacturing tolerance certification.'}
    acceptance=out/'assembly-drawing-acceptance.json';write_json(acceptance,proof)
    bom_csv=out/'assembly-drawing-bom.csv'
    with bom_csv.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(bom['headers']);writer.writerows(r['cells'] for r in bom['rows'])
    files=[Path(record['drawing_path']),pdf,preview,acceptance,bom_csv]+[Path(p) for p in record['model_hashes']]
    names={p.relative_to(out).as_posix():p for p in files};manifest={n:{'sha256':digest(p),'bytes':p.stat().st_size} for n,p in names.items()}
    hashes=out/'assembly-drawing-sha256.json';write_json(hashes,manifest)
    package=out/('assembly-drawing-package_'+stamp+'.zip')
    with zipfile.ZipFile(package,'x',zipfile.ZIP_DEFLATED) as archive:
        for name,path in names.items():archive.write(path,name)
        archive.write(hashes,hashes.name)
    with zipfile.ZipFile(package) as archive:
        if archive.testzip() is not None or any(hashlib.sha256(archive.read(n)).hexdigest()!=m['sha256'] for n,m in manifest.items()):raise RuntimeError('Assembly drawing dependency package failed integrity verification')
    record.update(verification=proof,package=str(package),package_verified=True,package_sha256=digest(package),preview=str(preview),pdf=str(pdf))
    closed=[]
    for path in [record['drawing_path'],record['assembly_path']]+list(record['models']):
        native=app.GetOpenDocumentByName(str(path))
        if native is None:continue
        if Path(get(native,'GetPathName')).resolve()!=Path(path).resolve() or bool(get(native,'GetSaveFlag')):
            raise RuntimeError('A task document changed before resource cleanup; not closed')
        app.CloseDoc(str(get(native,'GetTitle')));closed.append(Path(path).name)
    record['resource_cleanup']={'closed_task_documents':closed,'unowned_documents_preserved':True}

def execute_stage(app,spec_path,stage,allowed_root):
    source=Path(spec_path).resolve();out=source.parent;root=Path(allowed_root).resolve()
    if source.name!='assembly-drawing-spec.json' or not out.is_relative_to(root):raise ValueError('Invalid assembly drawing task location')
    spec=json.loads(source.read_text(encoding='utf8'));request=AssemblyDrawingRequest.model_validate(spec['request'])
    source_documents(spec,out)
    if type(stage) is not int or not 0<=stage<4:raise ValueError('Invalid assembly drawing stage')
    from .resource_budget import memory_status,require_headroom
    memory=memory_status();require_headroom(memory,opening=stage==0)
    marker=out/'assembly-drawing-progress.json';spec_hash=digest(source);stamp=hashlib.sha256(str(out).casefold().encode()).hexdigest()[:12]
    if stage==0:
        if marker.exists():raise ValueError('Drawing already started; use a new revision')
        record={'completed':0,'spec_sha256':spec_hash}
    else:
        record=json.loads(marker.read_text(encoding='utf8'))
        if record['completed']!=stage or record['spec_sha256']!=spec_hash:raise ValueError('Assembly drawing checkpoint mismatch; no write replayed')
        for path,expected in record['model_hashes'].items():
            if digest(path)!=expected:raise ValueError('A copied assembly dependency changed before execution')
    with (out/f'assembly-drawing-attempt-{stage}.json').open('x',encoding='utf8') as stream:json.dump({'stage':stage,'spec_sha256':spec_hash},stream)
    if stage==0:prepare(app,out,spec,request,record,stamp)
    elif stage==1:insert_bom(app,out,record)
    elif stage==2:insert_balloons(app,out,record)
    else:deliver(app,out,record,stamp)
    source_documents(spec,out);record['completed']=stage+1;write_json(marker,record)
    return {'status':'ok','stage':stage,'completed_stages':stage+1,'complete':stage==3,**record}
