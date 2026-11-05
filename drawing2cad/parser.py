"""Read exact DXF geometry; polygon samples are used only for validation/preview."""
from __future__ import annotations
import math,re
from pathlib import Path
from collections import Counter
import ezdxf
from ezdxf import units
from ezdxf.math import bulge_to_arc
from shapely.geometry import Polygon


class DrawingError(ValueError):
    pass


TOL=1e-5 # mm; endpoint matching only, never heal larger gaps
IGNORED_LAYERS=re.compile(r'(?:^|[_\- ])(?:DIM(?:ENSION)?S?|CENTER|CENTRE|HIDDEN|BORDER|TITLE|DEFPOINTS)(?:$|[_\- ])|标注|中心线|图框|隐藏线',re.I)


def _point(v,scale):
    if abs(float(v[2] if len(v)>2 else 0))*scale>TOL:raise DrawingError('图纸包含非平面几何，暂不转换。')
    result=[float(v[0])*scale,float(v[1])*scale]
    if not all(math.isfinite(x) and abs(x)<1e7 for x in result):raise DrawingError('图纸坐标超出支持范围。')
    return result


def samples(segment):
    kind=segment['kind']
    if kind=='line':return [segment['start'],segment['end']]
    c=segment['center'];r=segment['radius']
    if kind=='circle':a=0.;sweep=math.tau
    else:
        a=math.atan2(segment['start'][1]-c[1],segment['start'][0]-c[0])
        b=math.atan2(segment['end'][1]-c[1],segment['end'][0]-c[0])
        sweep=(b-a)%math.tau if segment['ccw'] else -((a-b)%math.tau)
    steps=max(8,math.ceil(abs(sweep)/(.01)))
    return [[c[0]+r*math.cos(a+sweep*i/steps),c[1]+r*math.sin(a+sweep*i/steps)] for i in range(steps+1)]


def signed_area(segments):
    total=0.
    for s in segments:
        if s['kind']=='circle':total+=math.pi*s['radius']**2;continue
        p,q=s['start'],s['end'];total+=(p[0]*q[1]-q[0]*p[1])/2
        if s['kind']=='arc':
            c=s['center'];a=math.atan2(p[1]-c[1],p[0]-c[0]);b=math.atan2(q[1]-c[1],q[0]-c[0])
            t=(b-a)%math.tau if s['ccw'] else -((a-b)%math.tau)
            total+=s['radius']**2*(t-math.sin(t))/2
    return total


def exact_bounds(segments):
    points=[]
    for s in segments:
        if s['kind']=='line':points.extend([s['start'],s['end']]);continue
        c=s['center'];r=s['radius']
        if s['kind']=='circle':points.extend([[c[0]-r,c[1]-r],[c[0]+r,c[1]+r]]);continue
        points.extend([s['start'],s['end']]);a=math.atan2(s['start'][1]-c[1],s['start'][0]-c[0]);b=math.atan2(s['end'][1]-c[1],s['end'][0]-c[0])
        span=(b-a)%math.tau if s['ccw'] else (a-b)%math.tau
        for theta in (0,math.pi/2,math.pi,3*math.pi/2):
            delta=(theta-a)%math.tau if s['ccw'] else (a-theta)%math.tau
            if delta<=span+1e-10:points.append([c[0]+r*math.cos(theta),c[1]+r*math.sin(theta)])
    return [min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)]


def _reverse(s):
    return {**s,'start':s['end'],'end':s['start'],**({'ccw':not s['ccw']} if s['kind']=='arc' else {})}


def _near(a,b):return math.dist(a,b)<=TOL


def _loops(segments):
    closed=[];edges=[];duplicates=0;seen=set()
    for s in segments:
        key=repr(s)
        if s['kind']!='circle':key=min(key,repr(_reverse(s)))
        if key in seen:duplicates+=1;continue
        seen.add(key)
        if s['kind']=='circle':closed.append([s])
        else:edges.append(s)
    while edges:
        chain=[edges.pop(0)]
        for _ in range(5000):
            if _near(chain[-1]['end'],chain[0]['start']):closed.append(chain);break
            choices=[]
            for i,s in enumerate(edges):
                if _near(chain[-1]['end'],s['start']):choices.append((i,s))
                elif _near(chain[-1]['end'],s['end']):choices.append((i,_reverse(s)))
            if len(choices)!=1:raise DrawingError('存在未闭合或分叉轮廓。请只保留建模视图轮廓，或将辅助线放到中心线/标注图层；程序不会自动补线。')
            i,s=choices[0];edges.pop(i);chain.append(s)
        else:raise DrawingError('轮廓过于复杂。')
    return closed,duplicates


def inspect_dxf(path,unit_override=None):
    try:doc=ezdxf.readfile(path)
    except (OSError,ezdxf.DXFError,UnicodeError) as exc:raise DrawingError('DXF文件无法读取，请重新导出有效DXF。') from exc
    count=len(doc.modelspace())
    if count>10000:raise DrawingError('图纸超过10000个实体，请先导出目标零件。')
    declared=int(doc.header.get('$INSUNITS',0))
    chosen={'mm':4,'cm':5,'m':6,'inch':1}.get(unit_override,declared)
    if not chosen:raise DrawingError('图纸没有长度单位，请补充“图纸单位毫米”或“图纸单位英寸”。')
    try:scale=units.conversion_factor(chosen,units.MM)
    except (ValueError,TypeError,KeyError) as exc:raise DrawingError('图纸长度单位暂不支持。') from exc
    if declared and unit_override and declared!=chosen:raise DrawingError('补充单位与DXF声明单位不一致，请先修正图纸单位。')
    ignored=Counter();unsupported=Counter();segments=[];dimensions=[]
    # Text/DIMENSION blocks are never decomposed into phantom part outlines.
    def entities(items,inherited=None,depth=0):
        if depth>12:raise DrawingError('图块嵌套过深。')
        for entity in items:
            if entity.dxftype()=='DIMENSION':yield entity;continue
            layer=str(entity.dxf.get('layer','0'))
            if layer=='0' and inherited:layer=inherited
            record=doc.layers.get(layer) if layer in doc.layers else None
            lt=str(entity.dxf.get('linetype','BYLAYER')).upper()
            if lt=='BYLAYER' and record:lt=str(record.dxf.linetype).upper()
            if IGNORED_LAYERS.search(layer) or (record and (record.is_off() or record.is_frozen())) or lt not in {'BYLAYER','BYBLOCK','CONTINUOUS'}:
                ignored['layer_or_linetype']+=1;continue
            if entity.dxftype()=='INSERT':
                if entity.mcount>1:raise DrawingError('阵列图块请先在CAD中分解。')
                yield from entities(entity.virtual_entities(),layer,depth+1)
            elif entity.dxftype()=='POLYLINE' and entity.is_2d_polyline:
                yield from entities(entity.virtual_entities(),layer,depth+1)
            else:yield entity
    for e in entities(doc.modelspace()):
        kind=e.dxftype()
        if kind=='DIMENSION':
            measured=e.get_measurement();text=str(e.dxf.get('text','<>')).strip()
            style=doc.dimstyles.get(e.dxf.dimstyle);factor=float(e.get_acad_dstyle({}).get('dimlfac',style.dxf.get('dimlfac',1.)))
            numeric=re.fullmatch(r'(?:[Ø⌀Rr]|%%[cC])?\s*([0-9]+(?:\.[0-9]+)?)',text)
            linear=(int(e.dxf.dimtype)&7) in {0,1,3,4,6}
            if isinstance(measured,(float,int)) and linear:
                shown=float(measured)*abs(factor)
                override=float(numeric.group(1)) if numeric else None
                conflict=(not math.isclose(abs(factor),1.,abs_tol=1e-8)
                    or (override is not None and not math.isclose(override,shown,abs_tol=.011))
                    or (text not in {'','<>',' '} and '<>' not in text and numeric is None))
                dimensions.append({'measurement_mm':float(measured)*scale,'display_text':text,'dimlfac':factor,'conflict':conflict})
            ignored[kind]+=1;continue
        if kind in {'TEXT','MTEXT','POINT','HATCH','SOLID','ATTDEF','ATTRIB','VIEWPORT'}:ignored[kind]+=1;continue
        extrusion=e.dxf.get('extrusion',(0.,0.,1.))
        if any(abs(float(a)-b)>1e-8 for a,b in zip(extrusion,(0,0,1))):raise DrawingError('包含反向或倾斜坐标系，请先转换为XY平面图纸。')
        if kind=='LINE':segments.append({'kind':'line','start':_point(e.dxf.start,scale),'end':_point(e.dxf.end,scale)})
        elif kind in {'CIRCLE','ARC'}:
            c=_point(e.dxf.center,scale);r=float(e.dxf.radius)*scale
            s={'kind':'circle' if kind=='CIRCLE' else 'arc','center':c,'radius':r}
            if kind=='ARC':
                a,b=[math.radians(v) for v in (e.dxf.start_angle,e.dxf.end_angle)]
                s.update(start=[c[0]+r*math.cos(a),c[1]+r*math.sin(a)],end=[c[0]+r*math.cos(b),c[1]+r*math.sin(b)],ccw=True)
            segments.append(s)
        elif kind=='LWPOLYLINE':
            if abs(e.dxf.elevation)*scale>TOL:raise DrawingError('多段线不在XY平面。')
            pts=list(e.get_points('xyb'))
            pairs=list(zip(pts,pts[1:]+pts[:1])) if e.closed else list(zip(pts,pts[1:]))
            for p,q in pairs:
                start,end=_point(p[:2],scale),_point(q[:2],scale)
                if abs(p[2])<1e-12:s={'kind':'line','start':start,'end':end}
                else:
                    c,_,_,r=bulge_to_arc(p[:2],q[:2],p[2])
                    s={'kind':'arc','start':start,'end':end,'center':_point(c,scale),'radius':float(r)*scale,'ccw':bool(p[2]>0)}
                segments.append(s)
        else:unsupported[kind]+=1
        if len(segments)>600:raise DrawingError('有效轮廓超过600段，请简化或单独导出零件。')
    if unsupported:raise DrawingError('有效图层含暂不支持的实体：'+', '.join(unsupported)+'。请导出LINE/ARC/CIRCLE/LWPOLYLINE轮廓。')
    if not segments:raise DrawingError('模型空间没有可用轮廓。请从模型空间导出目标视图。')
    for s in segments:
        if s['kind']=='line' and math.dist(s['start'],s['end'])<=TOL:raise DrawingError('存在零长度线段。')
        if 'radius' in s and (not math.isfinite(s['radius']) or s['radius']<=TOL):raise DrawingError('存在无效圆弧半径。')
    loops,duplicates=_loops(segments);records=[]
    for loop in loops:
        points=[]
        for s in loop:points.extend(samples(s)[:-1])
        polygon=Polygon(points)
        if not polygon.is_valid or polygon.area<TOL:raise DrawingError('轮廓自交或退化，请先修复图纸。')
        records.append({'segments':loop,'area_mm2':abs(signed_area(loop)),'polygon':polygon})
    for i,a in enumerate(records):
        for b in records[i+1:]:
            if a['polygon'].boundary.distance(b['polygon'].boundary)<TOL or (a['polygon'].intersects(b['polygon']) and not a['polygon'].contains(b['polygon']) and not b['polygon'].contains(a['polygon'])):
                raise DrawingError('视图轮廓相交或接触，无法确定实体边界。')
    roots=[a for a in records if not any(b is not a and b['polygon'].contains(a['polygon']) for b in records)]
    roots.sort(key=lambda a:(-a['area_mm2'],a['polygon'].bounds))
    views=[]
    for i,root in enumerate(roots,1):
        children=[r for r in records if r is not root and root['polygon'].contains(r['polygon'])]
        if any(a is not b and a['polygon'].contains(b['polygon']) for a in children for b in children):raise DrawingError('轮廓包含多层嵌套岛，请明确拆分实体。')
        views.append({'id':i,'bounds_mm':exact_bounds(root['segments']),'area_mm2':root['area_mm2']-sum(c['area_mm2'] for c in children),'outer':root['segments'],'inner':[c['segments'] for c in children]})
    return {'version':1,'source_name':Path(path).name,'units':chosen,'mm_per_unit':scale,'views':views,'dimensions':dimensions,'dimension_conflicts':sum(d['conflict'] for d in dimensions),'ignored':dict(ignored),'duplicate_entities_removed':duplicates,'geometry':'exact lines/arcs/circles; samples are validation only'}


def options(text):
    text=' '.join(text) if isinstance(text,list) else str(text)
    if re.search(r'盲孔|沉孔|沉头|螺纹|抽壳|放样|装配|拔模|旋转体|曲面|不(?:是|做|要)?通孔|不贯穿|blind|counterbore|countersink|thread|loft|assembly',text,re.I):
        raise DrawingError('这个精确图纸入口只支持等厚拉伸与贯穿内轮廓。检测到盲孔、沉孔、装配等其他特征要求，请另建工程任务明确尺寸；本次不会省略这些特征后继续建模。')
    thicknesses=re.findall(r'(?:厚度|板厚|厚|thickness\s*[=:]?)\s*([0-9]+(?:\.[0-9]+)?)\s*(毫米|mm|厘米|cm|英寸|inch|米|m)?',text,re.I)
    thickness=None
    if thicknesses:
        value,unit=thicknesses[-1];thickness=float(value)*{'厘米':10,'cm':10,'米':1000,'m':1000,'英寸':25.4,'inch':25.4}.get(unit.lower(),1)
        if not .01<=thickness<=2000:raise DrawingError('厚度必须在0.01至2000毫米之间。')
    unit=None
    m=re.search(r'(?:图纸单位|drawing units?)\s*(?:为|是|[:=])?\s*(毫米|mm|厘米|cm|英寸|inch|米|m)',text,re.I)
    if m:unit={'毫米':'mm','厘米':'cm','英寸':'inch','米':'m'}.get(m[1].lower(),m[1].lower())
    selected=re.findall(r'(?:视图|view)\s*([1-9][0-9]?)',text,re.I)
    return {'thickness_mm':thickness,'thickness_unit_explicit':bool(thicknesses and thicknesses[-1][1]),'unit_override':unit,'view_id':int(selected[-1]) if selected else None,
            'through':bool(re.search(r'通孔|贯穿|through',text,re.I)),
            'ignore_dimensions':bool(re.search(r'忽略标注|ignore dimensions',text,re.I))}


def select_spec(inspection,opts):
    views=inspection['views'];chosen=opts['view_id']
    questions=[]
    if len(views)>1 and chosen is None:questions.append('图纸有多个独立轮廓，请看识别图并指定“视图1”等编号。')
    if chosen is not None and chosen not in [v['id'] for v in views]:raise DrawingError('指定视图编号不存在。')
    view=next((v for v in views if v['id']==chosen),views[0])
    if opts['thickness_mm'] is None:questions.append('请说明拉伸厚度，例如“厚度8毫米”。')
    elif inspection['units']!=4 and not opts.get('thickness_unit_explicit'):questions.append('图纸不是毫米单位，请明确厚度单位，例如“厚度0.25英寸”。')
    if view['inner'] and not opts['through']:questions.append('请确认内轮廓是否全部贯穿，例如“所有内轮廓均为通孔”；盲孔、沉孔暂不由此入口推断。')
    if inspection['dimension_conflicts'] and not opts['ignore_dimensions']:questions.append('标注数值或比例与几何坐标存在冲突。请修正图纸，或明确“按几何建模，忽略标注”。')
    if questions:return None,'\n'.join(questions)
    if max(view['bounds_mm'][2]-view['bounds_mm'][0],view['bounds_mm'][3]-view['bounds_mm'][1])>2000:raise DrawingError('此入口支持最大2000毫米的零件。')
    return {**view,'thickness_mm':opts['thickness_mm'],'dimension_policy':'ignored_by_user' if opts['ignore_dimensions'] else 'checked_against_geometry','units':'mm'},None


def preview(inspection,path):
    from PIL import Image,ImageDraw,ImageFont
    views=inspection['views'];b=[v['bounds_mm'] for v in views]
    x0=min(v[0] for v in b);y0=min(v[1] for v in b);x1=max(v[2] for v in b);y1=max(v[3] for v in b)
    scale=min(1100/max(x1-x0,1),650/max(y1-y0,1))
    image=Image.new('RGB',(1200,800),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.load_default(size=22)
    def p(v):return (50+(v[0]-x0)*scale,720-(v[1]-y0)*scale)
    for view in views:
        for loop in [view['outer'],*view['inner']]:
            for s in loop:draw.line([p(v) for v in samples(s)],fill='#234c6c',width=3)
        draw.text(p([view['bounds_mm'][0],view['bounds_mm'][3]+10/scale]),'View '+str(view['id']),font=font,fill='#9b201e',anchor='ls')
    draw.text((40,755),'Exact vector contours; labels are view IDs. Units: mm',font=font,fill='black')
    image.save(path)
