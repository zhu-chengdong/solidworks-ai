"""Analytical visual-hull planning. Sampling validates; native curves build CAD.

Coordinates: TOP=(X,Y), FRONT=(X,Z), RIGHT=(Y,Z). Opposite/oblique
hole entries require explicit future support; never infer them from a circle.
"""
from __future__ import annotations
import math,re
from itertools import product
from shapely.geometry import Point,Polygon,LineString,box
from shapely.ops import unary_union
from .parser import DrawingError,samples,signed_area

AXES={'top':(0,1),'front':(0,2),'right':(1,2)}
HOLE_AXIS={'top':(2,-1),'front':(1,1),'right':(0,-1)}

def needs_analytic(data,opts):
    from .advanced import ROLES,_roles
    text=' '.join(a['text'] for a in data['annotations'])+' '+opts.get('request_text','')
    if re.search(r'\bCSK\b|COUNTERSINK|沉头|钻尖|锥底|\bPOINT\s*(?:ANGLE\s*)?\d',text,re.I):return True
    three=len(data['views'])==3 and (re.search('三视图',text) or all(re.search(pattern,text,re.I) for pattern in ROLES.values()))
    if not three:return False
    if any(s['kind']!='line' or (abs(s['start'][0]-s['end'][0])>1e-5 and abs(s['start'][1]-s['end'][1])>1e-5) for v in data['views'] for s in v['outer']):return True
    roles,q=_roles(data,opts)
    return not q and any(roles[k]['inner'] for k in ('front','right'))

def normalized(view):
    b=view['bounds_mm'];out=[]
    for s in view['outer']:
        s=dict(s)
        for key in ('start','end','center'):
            if key in s:s[key]=[s[key][0]-b[0],s[key][1]-b[1]]
        out.append(s)
    return out

def contour_polygon(segments):
    return Polygon([p for s in segments for p in samples(s)[:-1]])

def _on_arc(s,p):
    if s['kind']=='circle':return True
    c=s['center'];a=math.atan2(s['start'][1]-c[1],s['start'][0]-c[0]);b=math.atan2(s['end'][1]-c[1],s['end'][0]-c[0]);t=math.atan2(p[1]-c[1],p[0]-c[0])
    return ((t-a)%math.tau<=(b-a)%math.tau+1e-9) if s['ccw'] else ((a-t)%math.tau<=(a-b)%math.tau+1e-9)

def breaks(segments,axis):
    values=[]
    for s in segments:
        if s['kind']=='line':values.extend([s['start'][axis],s['end'][axis]])
        else:
            if s['kind']=='arc':values.extend([s['start'][axis],s['end'][axis]])
            for sign in (-1,1):
                p=list(s['center']);p[axis]+=sign*s['radius']
                if _on_arc(s,p):values.append(p[axis])
    return sorted({round(x,10) for x in values})

def intervals(segments,fixed_axis,value):
    """Exact line/circle intersections; half-open winding at line vertices."""
    other=1-fixed_axis;hits=[]
    # A tiny inward perturbation avoids tangent/vertex double crossings at
    # integration breakpoints without changing the actual native geometry.
    b=breaks(segments,fixed_axis)
    if any(abs(value-x)<1e-10 for x in b):value+=1e-8 if value<max(b)-1e-9 else -1e-8
    for s in segments:
        if s['kind']=='line':
            a,c=s['start'],s['end'];u,v=a[fixed_axis],c[fixed_axis]
            if (u<=value<v) or (v<=value<u):hits.append(a[other]+(value-u)/(v-u)*(c[other]-a[other]))
        else:
            d=value-s['center'][fixed_axis];r=s['radius']
            if abs(d)>=r:continue
            root=math.sqrt(max(0,r*r-d*d))
            for sign in (-1,1):
                p=list(s['center']);p[fixed_axis]=value;p[other]+=sign*root
                if _on_arc(s,p):hits.append(p[other])
    hits.sort()
    if len(hits)%2:raise DrawingError('轮廓交点不成对，不能推断实体区间。')
    return [(a,b) for a,b in zip(hits[::2],hits[1::2]) if b-a>1e-8]

def intersect(a,b):return [(max(x,u),min(y,v)) for x,y in a for u,v in b if min(y,v)-max(x,u)>1e-8]

def integrate(fn,a,b,tol=.0001,depth=18):
    def rec(a,b,fa,fm,fb,whole,tol,n):
        m=(a+b)/2;l=(a+m)/2;r=(m+b)/2;fl,fr=fn(l),fn(r)
        left=(m-a)*(fa+4*fl+fm)/6;right=(b-m)*(fm+4*fr+fb)/6;delta=left+right-whole
        if abs(delta)<=15*tol:return left+right+delta/15
        if n<=0:raise DrawingError('曲线体积积分未收敛，请简化视图。')
        return rec(a,m,fa,fl,fm,left,tol/2,n-1)+rec(m,b,fm,fr,fb,right,tol/2,n-1)
    if b-a<1e-9:return 0.
    fa,fm,fb=fn(a),fn((a+b)/2),fn(b)
    return rec(a,b,fa,fm,fb,(b-a)*(fa+4*fm+fb)/6,tol,depth)

def base_volume(profiles,size):
    # Exact signed areas for a single nonrectangular extrusion. More general
    # visual hulls use bounded adaptive integration of analytical intervals.
    nonrect=[k for k,p in profiles.items() if abs(abs(signed_area(p))-{'top':size[0]*size[1],'front':size[0]*size[2],'right':size[1]*size[2]}[k])>1e-6]
    if len(nonrect)<=1:
        role=nonrect[0] if nonrect else 'top';depth={'top':size[2],'front':size[1],'right':size[0]}[role]
        return abs(signed_area(profiles[role]))*depth,'analytical signed line/arc area × extrusion span'
    top,front,right=[profiles[k] for k in ('top','front','right')];yb=breaks(top,1)
    calls=0
    def area(z):
        nonlocal calls
        calls+=1
        if calls>18000:raise DrawingError('三视图组合超过积分复杂度上限。')
        xs=intervals(front,1,z);ys=intervals(right,1,z)
        def width(y):return sum(b-a for a,b in intersect(xs,intervals(top,1,y)))
        total=0.
        for a,b in ys:
            cuts=sorted({a,b,*[v for v in yb if a<v<b]})
            for lo,hi in zip(cuts,cuts[1:]):total+=integrate(width,lo,hi,tol=1e-6)
        return total
    zb=sorted(set(breaks(front,1)+breaks(right,1)))
    return sum(integrate(area,a,b,tol=.0005/max(1,len(zb)-1)) for a,b in zip(zb,zb[1:])),'adaptive integration of analytical line/arc section intervals; target error 0.0005 mm3'

def _axis_interval(profiles,axis,point):
    result=[(-1e6,1e6)]
    for role,(u,v) in AXES.items():
        if axis==u:result=intersect(result,intervals(profiles[role],1,point[v]))
        elif axis==v:result=intersect(result,intervals(profiles[role],0,point[u]))
        elif not contour_polygon(profiles[role]).buffer(.0001).covers(Point(point[u],point[v])):return []
    return result

def _hole_envelope(h,axis,u,v):
    p=h['entry_mm'];sign=h['direction'][axis];radius=h['counterbore_radius_mm'] or h['radius_mm'];end=p[axis]+sign*(h['cut_depth_mm']+h['drill_point_height_mm'])
    if axis not in (u,v):return Point(p[u],p[v]).buffer(radius+.01,resolution=128)
    # Bounding rectangle is deliberately conservative for drill tips/cones.
    other=v if axis==u else u;lo,hi=sorted((p[axis],end))
    return box(lo,p[other]-radius-.01,hi,p[other]+radius+.01) if axis==u else box(p[other]-radius-.01,lo,p[other]+radius+.01,hi)

def _hidden(data,spec,views):
    count=0;L,W,_=spec['size_mm'];offset=[L/2,W/2,0]
    for line in data.get('hidden_segments',[]):
        source=LineString(line);matches=[(role,v) for role,v in views.items() if contour_polygon(v['outer']).buffer(.0001).covers(source)]
        if len(matches)!=1:raise DrawingError('隐藏线无法唯一关联视图。')
        role,v=matches[0];u,w=AXES[role];b=v['bounds_mm'];actual=LineString([[x-b[0]-offset[u],y-b[1]-offset[w]] for x,y in line]);expected=[]
        for h in spec['holes']:
            axis=h['axis_index']
            if axis not in (u,w):continue
            p=h['entry_mm'];sign=h['direction'][axis];other=w if axis==u else u
            def xy(t,r):
                q=list(p);q[axis]+=sign*t;q[other]+=r;return [q[u],q[w]]
            r=h['radius_mm'];R=h['counterbore_radius_mm'];d=h['cut_depth_mm'];recess=h['counterbore_depth_mm'] or 0.;csk=h['countersink_angle_deg']
            for s in (-1,1):
                expected.append(LineString([xy(recess,s*r),xy(d,s*r)]))
                if R is not None:
                    expected.append(LineString([xy(0,s*R),xy(recess,s*r if csk else s*R)]))
                    if not csk:expected.append(LineString([xy(recess,s*R),xy(recess,s*r)]))
                if h['drill_point_height_mm']:expected.append(LineString([xy(d,s*r),xy(d+h['drill_point_height_mm'],0)]))
            if not h['through'] and not h['drill_point_height_mm']:expected.append(LineString([xy(d,-r),xy(d,r)]))
        if not expected or actual.difference(unary_union(expected).buffer(.001)).length>.002:raise DrawingError('隐藏线不能由已标注孔特征解释，请补充剖视或完整特征；不会按实心忽略。')
        count+=1
    return count

def plan_analytic(data,opts):
    from .advanced import _roles,_hole_notes
    text=' '.join(a['text'] for a in data['annotations'])+' '+opts.get('request_text','')
    if re.search(r'螺纹|\bTHREAD|锥孔(?!口)|左视|后视|底视|\b(?:LEFT|REAR|BOTTOM)\s+VIEW\b|\bFROM\s+(?:BACK|REAR|LEFT|BOTTOM)\b|反向孔|斜孔|斜向孔',text,re.I):raise DrawingError('当前入口不推断螺纹、锥度孔、反向或倾斜孔轴；请提供明确工程特征。')
    three=len(data['views'])==3 or bool(re.search('三视图',text))
    if three:
        views,q=_roles(data,opts)
        if q:return None,'\n'.join(q)
        profiles={k:normalized(v) for k,v in views.items()};bounds={k:v['bounds_mm'] for k,v in views.items()}
        L=bounds['top'][2]-bounds['top'][0];W=bounds['top'][3]-bounds['top'][1];H=bounds['front'][3]-bounds['front'][1]
        if max(abs(bounds['front'][2]-bounds['front'][0]-L),abs(bounds['right'][2]-bounds['right'][0]-W),abs(bounds['right'][3]-bounds['right'][1]-H))>1e-4:raise DrawingError('三视图长、宽、高不一致。')
    else:
        selected=opts['view_id'];views_all=data['views']
        if len(views_all)>1 and selected is None:return None,'请指定视图编号。'
        view=next((v for v in views_all if v['id']==selected),views_all[0] if selected is None else None)
        if view is None:raise DrawingError('指定视图不存在。')
        if opts['thickness_mm'] is None:return None,'请补充厚度及单位。'
        if data['units']!=4 and not opts.get('thickness_unit_explicit'):return None,'请明确厚度单位。'
        b=view['bounds_mm'];L,W,H=b[2]-b[0],b[3]-b[1],opts['thickness_mm'];views={'top':view}
        def rect(w,h):return [{'kind':'line','start':a,'end':b} for a,b in zip([[0,0],[w,0],[w,h],[0,h]],[[w,0],[w,h],[0,h],[0,0]])]
        profiles={'top':normalized(view),'front':rect(L,H),'right':rect(W,H)}
    size=[L,W,H]
    if min(size)<=.05 or max(size)>2000:raise DrawingError('零件尺寸超出0.05至2000毫米范围。')
    if sum(len(v) for v in profiles.values())>180:raise DrawingError('三视图轮廓超过180段。')
    if data['dimension_conflicts'] and not opts['ignore_dimensions']:return None,'尺寸标注与几何冲突，请修正或明确忽略标注。'
    holes=[];questions=[];offset=[L/2,W/2,0]
    for role,v in views.items():
        notes,q=_hole_notes(data,v,opts);questions+=q;u,w=AXES[role];axis,sign=HOLE_AXIS[role];b=v['bounds_mm']
        for h in notes:
            p=[0.,0.,0.];p[u]=h['center_drawing_mm'][0]-b[0];p[w]=h['center_drawing_mm'][1]-b[1]
            ranges=_axis_interval(profiles,axis,p)
            if len(ranges)!=1:raise DrawingError(f"{h['id']}孔轴穿过零段或多段材料，需补充结构。")
            low,high=ranges[0];entry=high if sign<0 else low;span=high-low;p[axis]=entry
            radius=h['counterbore_radius_mm'] or h['radius_mm']
            # Verify the entire entry circle lies on a constant planar entry.
            others=[i for i in range(3) if i!=axis]
            for j in range(64):
                q=list(p);q[others[0]]+=(radius+.01)*math.cos(math.tau*j/64);q[others[1]]+=(radius+.01)*math.sin(math.tau*j/64)
                values=_axis_interval(profiles,axis,q)
                if len(values)!=1 or abs(values[0][1 if sign<0 else 0]-entry)>1e-4 or (h['through'] and abs(values[0][0 if sign<0 else 1]-(low if sign<0 else high))>1e-4):raise DrawingError(f"{h['id']}孔口/贯穿出口不在完整平面，或跨越曲面、斜面及外边界；请明确局部结构。")
            depth=span if h['through'] else h['depth_mm'];tip=h['drill_point_height_mm']
            if depth is None or not math.isfinite(depth) or depth<=.01 or depth+tip>span+.0001 or (not h['through'] and depth+tip>=span-.05):raise DrawingError(f"{h['id']}孔深及钻尖必须小于局部厚度{span:g}毫米，并保留底壁。")
            recess=h['counterbore_depth_mm']
            if recess is not None and not .01<recess<depth-.01:raise DrawingError(f"{h['id']}沉孔/沉头深度必须小于圆柱孔深度。")
            direction=[0,0,0];direction[axis]=sign
            h.update(axis='xyz'[axis],axis_index=axis,direction=direction,entry_mm=p,cut_depth_mm=depth,view_role=role)
            for proj,(a,c) in AXES.items():
                if not contour_polygon(profiles[proj]).buffer(.0002).covers(_hole_envelope(h,axis,a,c)):raise DrawingError(f"{h['id']}孔段或钻尖越过外轮廓，暂不自动推断局部交线。")
            h['entry_mm']=[x-o for x,o in zip(p,offset)];holes.append(h)
    if questions:return None,'\n'.join(questions)
    if len({h['id'] for h in holes})!=len(holes):raise DrawingError('不同视图的孔编号重复，请明确每个孔的唯一入孔视图。')
    if len(holes)>24:raise DrawingError('孔数量超过24。')
    for i,h in enumerate(holes):
        p=h['entry_mm'];axis=h['axis_index'];r=h['counterbore_radius_mm'] or h['radius_mm'];q=[a+d*(h['cut_depth_mm']+h['drill_point_height_mm']) for a,d in zip(p,h['direction'])]
        h['envelope_mm']=[[min(p[j],q[j])-(r+.01 if j!=axis else 0),max(p[j],q[j])+(r+.01 if j!=axis else 0)] for j in range(3)]
        for previous in holes[:i]:
            if all(min(a[1],b[1])-max(a[0],b[0])>-.01 for a,b in zip(h['envelope_mm'],previous['envelope_mm'])):raise DrawingError('孔段包络相交，需明确交叉孔结构；不会重复扣除体积。')
    volume,method=base_volume(profiles,size);removed=0.
    for h in holes:
        r=h['radius_mm'];R=h['counterbore_radius_mm'];d=h['counterbore_depth_mm'] or 0
        removed+=math.pi*r*r*(h['cut_depth_mm']+h['drill_point_height_mm']/3)
        if R is not None:removed+=math.pi*d*((R*R+R*r+r*r)/3-r*r) if h['countersink_angle_deg'] else math.pi*(R*R-r*r)*d
    details={k:[] for k in views}
    for role,v in views.items():
        b=v['bounds_mm'];poly=contour_polygon(v['outer']).buffer(.0001)
        for segment in data.get('detail_segments',[]):
            if poly.covers(LineString(samples(segment))):
                s=dict(segment)
                for key in ('start','end','center'):
                    if key in s:s[key]=[s[key][0]-b[0],s[key][1]-b[1]]
                details[role].append(s)
    spec={'version':3,'kind':'orthographic_analytic','id':views['top']['id'],'size_mm':size,'profiles':profiles,'views':{k:v['id'] for k,v in views.items()},'detail_curves':details,'holes':holes,'base_volume_mm3':volume,'volume_method':method,'expected_volume_mm3':volume-removed,'units':'mm','dimension_policy':'ignored_by_user' if opts['ignore_dimensions'] else 'checked_against_geometry','assumptions':['外形为三个正交轮廓的棱柱交集；未显示内部区域按实心处理，隐藏线必须由孔特征解释。','原生直线、圆弧、圆和旋转切除；不将采样折线作为CAD几何。','孔从TOP最大Z、FRONT最小Y、RIGHT最大X的完整平面入孔。']}
    spec['hidden_lines_checked']=_hidden(data,spec,views)
    if spec['expected_volume_mm3']<=0:raise DrawingError('剩余体积无效。')
    return spec,None
