"""Dimensioned orthographic reconstruction and leader-associated hole callouts.

The multiview solver intersects orthogonal prismatic silhouettes exactly. It
does not infer unshown cavities or arbitrary curved/freeform solids.
"""
from __future__ import annotations
import math,re
from itertools import product
from shapely.geometry import Polygon,Point,box
from shapely.ops import unary_union
from .parser import DrawingError,samples,signed_area

ROLES={'front':r'主视(?:图)?|\bFRONT\b','top':r'俯视(?:图)?|\bTOP\b','right':r'右视(?:图)?|\bRIGHT\b'}


def polygon(view):
    return Polygon([p for segment in view['outer'] for p in samples(segment)[:-1]])


def _roles(data,opts):
    assigned={};views=data['views'];questions=[]
    for role,pattern in ROLES.items():
        explicit=re.findall({'front':'主视图','top':'俯视图','right':'右视图'}[role]+r'\s*(?:为|是|=|:)?\s*(?:视图)?\s*([1-9][0-9]?)',opts.get('request_text',''))
        if explicit:
            selected=[v for v in views if v['id']==int(explicit[-1])]
            if len(selected)!=1:raise DrawingError('指定的三视图编号不存在。')
            assigned[role]=selected[0];continue
        labels=[a for a in data['annotations'] if re.fullmatch(r'\s*(?:'+pattern+r')\s*',a['text'],re.I)]
        if len(labels)==1:
            p=Point(labels[0]['point_mm']);rank=sorted([(polygon(v).distance(p),v['id'],v) for v in views],key=lambda r:r[0])
            if len(rank)>1 and abs(rank[0][0]-rank[1][0])<1e-5:raise DrawingError('视图标识与轮廓对应不明确，请指定主视图、俯视图和右视图编号。')
            assigned[role]=rank[0][2]
        elif labels:raise DrawingError('存在重复视图标识，请单独导出目标零件。')
    if len(assigned)!=3 or len({v['id'] for v in assigned.values()})!=3:
        questions.append('请标明主视图、俯视图和右视图，例如“主视图为视图2，俯视图为视图1，右视图为视图3”。')
    if len(views)!=3:questions.append('三视图重建需要三个独立外轮廓；请只保留同一个零件的主视、俯视和右视图。')
    return assigned,questions


def _normalized(view):
    b=view['bounds_mm'];points=[]
    for s in view['outer']:
        if s['kind']!='line' or (abs(s['start'][0]-s['end'][0])>1e-5 and abs(s['start'][1]-s['end'][1])>1e-5):
            raise DrawingError('当前三视图外形支持直角阶梯轮廓；斜面或曲线外形需要另行给出建模特征，不能以折线近似。')
        points.append([s['start'][0]-b[0],s['start'][1]-b[1]])
    return Polygon(points)


def multiview(data,opts):
    views,questions=_roles(data,opts)
    if questions:return None,questions
    p={k:_normalized(v) for k,v in views.items()};f,t,r=[p[k] for k in ('front','top','right')]
    L,W,H=t.bounds[2],t.bounds[3],f.bounds[3]
    if max(L,W,H)>2000 or min(L,W,H)<=.05:raise DrawingError('三视图尺寸超出0.05至2000毫米范围。')
    if max(abs(f.bounds[2]-L),abs(r.bounds[2]-W),abs(r.bounds[3]-H))>1e-4:raise DrawingError('三视图长、宽、高不一致，请检查比例、单位或视图对应。')
    xs=sorted({round(v[0],8) for name in ('front','top') for v in p[name].exterior.coords})
    ys=sorted({round(v[1] if name=='top' else v[0],8) for name in ('top','right') for v in p[name].exterior.coords})
    zs=sorted({round(v[1],8) for name in ('front','right') for v in p[name].exterior.coords})
    if (len(xs)-1)*(len(ys)-1)*(len(zs)-1)>1500:raise DrawingError('三视图分段过多，请单独导出目标零件。')
    cells=[]
    for (x0,x1),(y0,y1),(z0,z1) in product(zip(xs,xs[1:]),zip(ys,ys[1:]),zip(zs,zs[1:])):
        x,y,z=(x0+x1)/2,(y0+y1)/2,(z0+z1)/2
        if t.covers(Point(x,y)) and f.covers(Point(x,z)) and r.covers(Point(y,z)):cells.append([x0-L/2,y0-W/2,z0,x1-L/2,y1-W/2,z1])
    if not cells:raise DrawingError('三视图没有共同实体。')
    projections={
        'top':unary_union([box(c[0]+L/2,c[1]+W/2,c[3]+L/2,c[4]+W/2) for c in cells]),
        'front':unary_union([box(c[0]+L/2,c[2],c[3]+L/2,c[5]) for c in cells]),
        'right':unary_union([box(c[1]+W/2,c[2],c[4]+W/2,c[5]) for c in cells])}
    if any(projections[k].symmetric_difference(p[k]).area>1e-5 for k in p):raise DrawingError('三个外轮廓无法重投影为一致实体，请检查缺失线条或视图对应。')
    layers=[]
    for z0,z1 in zip(zs,zs[1:]):
        footprint=unary_union([box(c[0],c[1],c[3],c[4]) for c in cells if abs(c[2]-z0)<1e-6])
        if footprint.is_empty:continue
        if layers and layers[-1]['polygon'].equals(footprint) and abs(layers[-1]['z1']-z0)<1e-6:layers[-1]['z1']=z1
        else:layers.append({'polygon':footprint,'z0':z0,'z1':z1})
    if len(layers)>12:raise DrawingError('三视图产生超过12个高度层，暂不自动建模。')
    serialized=[]
    for layer in layers:
        polys=list(layer['polygon'].geoms) if layer['polygon'].geom_type=='MultiPolygon' else [layer['polygon']]
        if any(poly.interiors for poly in polys):raise DrawingError('三视图外轮廓存在无法辨别深度的封闭腔体，请补充剖视图。')
        serialized.append({'z0':layer['z0'],'z1':layer['z1'],'profiles':[[list(v) for v in poly.exterior.coords[:-1]] for poly in polys]})
    expected={k:[list(v) for v in poly.exterior.coords[:-1]] for k,poly in p.items()};details={k:[] for k in views}
    from shapely.geometry import LineString
    for role,view in views.items():
        boundary=polygon(view).buffer(1e-5);b=view['bounds_mm']
        for s in data.get('detail_segments',[]):
            if boundary.covers(LineString([s['start'],s['end']])):details[role].append([[point[0]-b[0],point[1]-b[1]] for point in (s['start'],s['end'])])
    return {'kind':'orthographic','size_mm':[L,W,H],'layers':serialized,'cells':cells,'views':{k:v['id'] for k,v in views.items()},'projections':expected,'detail_lines':details,'base_volume_mm3':sum((c[3]-c[0])*(c[4]-c[1])*(c[5]-c[2]) for c in cells),'top_view':views['top'],'assumptions':['三视图中未标注的内部区域按实心处理；仅支持相互一致的直角阶梯外轮廓。']},[]


def _hole_notes(data,view,opts):
    circles=[]
    for loop in view['inner']:
        if len(loop)!=1 or loop[0]['kind']!='circle':raise DrawingError('带深度图纸的内轮廓目前需要圆孔；非圆盲腔或槽需单独提供深度特征。')
        c=loop[0];group=next((g for g in circles if math.dist(g['center'],c['center'])<1e-4),None)
        if group is None:group={'center':c['center'],'radii':[]};circles.append(group)
        if not any(abs(c['radius']-r)<1e-4 for r in group['radii']):group['radii'].append(c['radius'])
    notes=[]
    for lead in data['leaders']:
        if len(lead['points_mm'])<2:continue
        arrow,tail=lead['points_mm'][0],lead['points_mm'][-1]
        groups=[g for g in circles if math.dist(arrow,g['center'])<=max(g['radii'])+.05]
        if not groups:continue
        if len(groups)!=1:raise DrawingError('孔标注引线对应多个孔，请修正引线。')
        ranked=sorted([(math.dist(tail,a['point_mm']),a) for a in data['annotations'] if re.search(r'\bH\d+\b|盲孔|沉孔|BLIND|CBORE|DIA|[Ø⌀]',a['text'],re.I)],key=lambda r:r[0])
        if not ranked or ranked[0][0]>15:continue
        if len(ranked)>1 and abs(ranked[0][0]-ranked[1][0])<1e-5:raise DrawingError('孔引线末端存在多个同距标注。')
        group=groups[0]
        if 'note' in group and group['note']!=ranked[0][1]['text']:raise DrawingError('同一孔存在相互冲突的标注。')
        group['note']=ranked[0][1]['text'];group['leader_handle']=lead['handle']
    questions=[]
    for i,g in enumerate(circles,1):
        text=g.get('note','');id_match=re.search(r'\bH\d+\b',text,re.I);hole_id=id_match[0].upper() if id_match else 'H'+str(i)
        overrides=re.findall(r'\b'+hole_id+r'\b([^;；\n]*)',opts.get('request_text',''),re.I)
        if overrides:
            extra=overrides[-1]
            if re.search(r'DIA|[Ø⌀]',extra,re.I):text=hole_id+' '+extra
            elif re.search(r'CBORE|COUNTERBORE|沉孔|⌴',text,re.I) and re.search(r'DEPTH|深|↧',extra,re.I):
                raise DrawingError(f'{hole_id}有两级孔深，请完整补充底孔和沉孔规格，例如“H3 DIA8 BLIND DEPTH20 CBORE DIA14 DEPTH6”。')
            else:text+=' '+extra
        text=text.replace('%%c','DIA').replace('%%C','DIA').replace('Φ','Ø').replace('φ','Ø').replace('直径','DIA')
        factor=data['mm_per_unit'];radii=sorted(g['radii'])
        dia=[float(v)*factor for v in re.findall(r'(?:DIA(?:METER)?|[Ø⌀])\s*([0-9]+(?:\.[0-9]+)?)',text,re.I)]
        cb=re.search(r'CBORE|COUNTERBORE|沉孔|⌴',text,re.I)
        base_text=text[:cb.start()] if cb else text
        blind=bool(re.search(r'BLIND|盲孔|不贯穿|非通孔|非贯穿|不(?:是)?通孔|NOT\s+THR(?:OUGH|U)|DEPTH|深|↧',base_text,re.I));through=bool(re.search(r'THRU|THROUGH|通孔|贯穿',base_text,re.I)) and not blind
        depths=[float(v)*factor for v in re.findall(r'(?:DEPTH|深(?:度)?|↧)\s*([0-9]+(?:\.[0-9]+)?)',text,re.I)]
        if not text and len(radii)==1 and opts['through']:through=True;dia=[2*radii[0]]
        if not dia or abs(dia[0]-2*radii[0])>1e-4:questions.append(f'{hole_id}缺少或冲突的孔径标注，请用引线关联DIA/Ø直径。');continue
        if cb:
            if len(radii)!=2 or len(dia)!=2 or abs(dia[1]-2*radii[1])>1e-4:questions.append(f'{hole_id}沉孔需要两级同心圆和匹配的两级直径标注。');continue
            before,after=text[:cb.start()],text[cb.end():]
            cbdepth=re.findall(r'(?:DEPTH|深(?:度)?|↧)\s*([0-9]+(?:\.[0-9]+)?)',after,re.I)
            basedepth=re.findall(r'(?:DEPTH|深(?:度)?|↧)\s*([0-9]+(?:\.[0-9]+)?)',before,re.I)
            if not cbdepth or (not through and not basedepth):questions.append(f'{hole_id}请补充底孔深度/贯穿状态和沉孔深度。');continue
            depth=float(basedepth[-1])*factor if basedepth else None;cb_depth=float(cbdepth[-1])*factor
        else:
            if len(radii)!=1:questions.append(f'{hole_id}同心圆未注明沉孔或沉头规格，不能推断。');continue
            if not through and not (blind and depths):questions.append(f'{hole_id}请注明盲孔深度或通孔状态，例如“H1 BLIND DEPTH10”。');continue
            depth=depths[-1] if blind else None;cb_depth=None
        notes.append({'id':hole_id,'center_drawing_mm':g['center'],'radius_mm':radii[0],'through':through,'depth_mm':depth,'counterbore_radius_mm':radii[-1] if cb else None,'counterbore_depth_mm':cb_depth,'source_text':text,'leader_handle':g.get('leader_handle'),'kind':'counterbore' if cb else 'through' if through else 'blind'})
    if len({n['id'] for n in notes})!=len(notes):raise DrawingError('孔标注编号重复，请给每个孔唯一H编号。')
    return notes,questions


def plan_advanced(data,opts):
    text=' '.join(a['text'] for a in data['annotations'])+' '+opts.get('request_text','')
    if re.search(r'\bCSK\b|COUNTERSINK|沉头|锥底|锥孔|螺纹|\bTHREAD',text,re.I):raise DrawingError('图纸含沉头、锥底或螺纹要求，当前深度入口仅支持平底盲孔和圆柱沉孔，不能省略这些要求后继续。')
    three=bool(re.search('三视图',text)) or all(re.search(p,text,re.I) for p in ROLES.values())
    questions=[]
    if three:
        spec,questions=multiview(data,opts)
        if questions:return None,'\n'.join(questions)
        view=spec.pop('top_view')
        other=[v for v in data['views'] if v['id']!=view['id']]
        if any(v['inner'] for v in other):raise DrawingError('当前孔深重建支持俯视图中的Z向孔；侧向孔需另行定义，不能忽略。')
    else:
        views=data['views'];selected=opts['view_id']
        if len(views)>1 and selected is None:return None,'请指定需要建模的视图编号；需要三视图重建请明确主视、俯视和右视图。'
        view=next((v for v in views if v['id']==selected),views[0] if selected is None else None)
        if view is None:raise DrawingError('指定视图不存在。')
        if opts['thickness_mm'] is None:return None,'请补充零件厚度，例如“厚度20毫米”。'
        b=view['bounds_mm'];L,W=b[2]-b[0],b[3]-b[1];H=opts['thickness_mm']
        spec={'kind':'profile_holes','size_mm':[L,W,H],'outer':view['outer'],'bounds_mm':b,'base_volume_mm3':abs(signed_area(view['outer']))*H,'views':{'top':view['id']},'assumptions':[]}
    if data['units']!=4 and not three and not opts.get('thickness_unit_explicit'):return None,'请明确厚度单位。'
    if max(spec['size_mm'])>2000:raise DrawingError('零件最大尺寸不能超过2000毫米。')
    if data['dimension_conflicts'] and not opts['ignore_dimensions']:return None,'尺寸标注与几何冲突，请修正图纸或明确忽略标注。'
    holes,hole_questions=_hole_notes(data,view,opts)
    if hole_questions:return None,'\n'.join(hole_questions)
    if any(not h['through'] for h in holes) and not re.search(r'FLAT[ _-]?BOTTOM|平底',text,re.I):
        return None,'请确认盲孔底部为平底，例如回复“盲孔均为平底”；带钻尖或锥底的孔需要注明钻尖角度，当前入口不会猜测。'
    L,W,H=spec['size_mm'];b=view['bounds_mm'];origin=[b[0]+L/2,b[1]+W/2]
    for hole in holes:
        x,y=[v-o for v,o in zip(hole['center_drawing_mm'],origin)];radius=hole['counterbore_radius_mm'] or hole['radius_mm'];p=Point(x,y)
        if spec['kind']=='orthographic':
            layers=[l for l in spec['layers'] if unary_union([Polygon(s) for s in l['profiles']]).contains(p)]
            if not layers:raise DrawingError('孔中心不在三视图实体内部。')
            entry=max(l['z1'] for l in layers);bottom=min(l['z0'] for l in layers)
            if any(abs(a['z1']-c['z0'])>1e-5 for a,c in zip(layers,layers[1:])):raise DrawingError('孔轴穿过多段材料，暂不自动推断孔深。')
            for layer in layers:
                poly=unary_union([Polygon(s) for s in layer['profiles']])
                if poly.boundary.distance(p)<=radius+.05:raise DrawingError('孔或沉孔跨越阶梯边界/外轮廓，请明确局部结构。')
        else:
            base=polygon(view);p_original=Point(hole['center_drawing_mm'])
            if base.boundary.distance(p_original)<=radius+.05:raise DrawingError('孔靠近或越过外轮廓。')
            entry,bottom=H,0.
        length=entry-bottom;depth=length if hole['through'] else hole['depth_mm']
        if depth is None or not math.isfinite(depth) or depth<=.01 or depth>length+1e-5 or (not hole['through'] and depth>=length-.05):raise DrawingError(f"{hole['id']}盲孔深度必须小于局部材料厚度{length:g}毫米，并保留底壁。")
        if hole['counterbore_depth_mm'] is not None and not .01<hole['counterbore_depth_mm']<depth-.01:raise DrawingError(f"{hole['id']}沉孔深度必须小于底孔深度。")
        hole.update(x_mm=x,y_mm=y,entry_z_mm=entry,bottom_z_mm=entry-depth,cut_depth_mm=depth,axis='z')
    for a,c in product(holes,repeat=2):
        if a is c:continue
        if math.hypot(a['x_mm']-c['x_mm'],a['y_mm']-c['y_mm'])<=(a['counterbore_radius_mm'] or a['radius_mm'])+(c['counterbore_radius_mm'] or c['radius_mm'])+.05:raise DrawingError('孔段或沉孔相交，暂不自动建模。')
    removed=sum(math.pi*h['radius_mm']**2*h['cut_depth_mm']+(math.pi*((h['counterbore_radius_mm'] or h['radius_mm'])**2-h['radius_mm']**2)*(h['counterbore_depth_mm'] or 0)) for h in holes)
    # Unknown hidden geometry can represent an internal cavity. Never drop it
    # while declaring a complete solid reconstructed from the three views.
    hidden_count=0
    if data.get('hidden_segments'):
        from shapely.geometry import LineString
        if spec['kind']!='orthographic':raise DrawingError('单视图含隐藏结构，请提供完整三视图以检查孔深投影。')
        for line in data['hidden_segments']:
            geometry=LineString(line);matches=[]
            for role,view_id in spec['views'].items():
                v=next(v for v in data['views'] if v['id']==view_id)
                if polygon(v).buffer(1e-4).covers(geometry):matches.append((role,v))
            if len(matches)!=1:raise DrawingError('隐藏线无法唯一关联到某一视图，请检查图纸。')
            role,v=matches[0];b=v['bounds_mm'];normalized=LineString([[x-b[0],y-b[1]] for x,y in line]);expected=[]
            if role in {'front','right'}:
                for h in holes:
                    center=h['x_mm']+L/2 if role=='front' else h['y_mm']+W/2
                    expected.append(box(center-h['radius_mm'],h['bottom_z_mm'],center+h['radius_mm'],h['entry_z_mm']).boundary)
                    if h['counterbore_radius_mm'] is not None:expected.append(box(center-h['counterbore_radius_mm'],h['entry_z_mm']-h['counterbore_depth_mm'],center+h['counterbore_radius_mm'],h['entry_z_mm']).boundary)
            if not expected or normalized.difference(unary_union(expected).buffer(.001)).length>.002:
                raise DrawingError('图纸包含无法由已识别孔标注解释的隐藏线，可能有腔体或其他内部结构；请补充剖视或特征说明，不能按实心忽略。')
            hidden_count+=1
    spec.update(version=2,id=view['id'],holes=holes,hidden_lines_checked=hidden_count,expected_volume_mm3=spec['base_volume_mm3']-removed,dimension_policy='ignored_by_user' if opts['ignore_dimensions'] else 'checked_against_geometry',units='mm')
    if len(holes)>24 or spec['expected_volume_mm3']<=0:raise DrawingError('孔数量或剩余体积无效。')
    return spec,None
