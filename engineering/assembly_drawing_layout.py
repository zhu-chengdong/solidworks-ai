"""Bounded matching of native leader tips to nonoverlapping perimeter balloons."""
import math

def project_component(point,pose,view):
    """Part-local curve point -> assembly -> actual drawing sheet (metres)."""
    model=[pose[12]*sum(pose[c*3+r]*point[c] for c in range(3))+pose[9+r] for r in range(3)]
    return [view[12]*sum(view[c*3+r]*model[c] for c in range(3))+view[9+r] for r in range(3)]

def point_segment_distance(point,a,b):
    length=sum((y-x)**2 for x,y in zip(a,b))
    t=max(0.,min(1.,sum((p-x)*(y-x) for p,x,y in zip(point,a,b))/length)) if length else 0.
    return math.dist(point,[x+t*(y-x) for x,y in zip(a,b)])

def select_tip(edges,others):
    """Choose an interior point with separation from other part outlines.

    Native edge identity is retained. Curved edges are tessellated through
    their actual curve parameters before calling this pure geometry helper.
    The visual reviewer remains responsible for occlusion/semantic clarity.
    """
    candidates=[]
    for index,points in enumerate(edges):
        for a,b in zip(points,points[1:]):
            if math.dist(a[:2],b[:2])<.0004:continue
            for t in (.5,.3,.7):
                p=[x+t*(y-x) for x,y in zip(a,b)]
                clearance=min((point_segment_distance(p[:2],c[:2],d[:2]) for line in others for c,d in zip(line,line[1:])),default=.02)
                # Stay away from target vertices too; they often coincide
                # with neighbouring part outlines at a joint.
                end_clearance=min(math.dist(p[:2],a[:2]),math.dist(p[:2],b[:2]))
                candidates.append((min(clearance,end_clearance),clearance,index,p))
    if not candidates:raise ValueError('No sufficiently long projected visible edge for a balloon attachment')
    chosen=max(candidates,key=lambda v:(v[0],v[1]))
    return chosen[2],chosen[3],chosen[0]

def overlaps(a,b,padding=0.):
    return min(a[2]+padding,b[2])-max(a[0]-padding,b[0])>0 and min(a[3]+padding,b[3])-max(a[1]-padding,b[1])>0

def intersects(a,b,c,d):
    def cross(p,q,r):return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    return cross(a,b,c)*cross(a,b,d)<-1e-14 and cross(c,d,a)*cross(c,d,b)<-1e-14

def crossing_count(segments):
    return sum(intersects(a,b,c,d) for i,(a,b) in enumerate(segments) for c,d in segments[i+1:])

def arrange(tips):
    count=len(tips)
    if not 1<=count<=24:raise ValueError('Balloon layout requires1-24 actual component tips')
    names=sorted(tips);anchors=[]
    for x,n in ((.035,(count+1)//2),(.215,count//2)):
        anchors.extend((x,.255-(.115*i/max(1,n-1))) for i in range(n))
    if any(len(point)!=2 or not all(math.isfinite(v) for v in point) for point in tips.values()):raise ValueError('Native leader tips must be finite sheet points')
    cost=[[math.dist(tips[name],point) for point in anchors] for name in names]
    # Bounded Hungarian assignment, implemented with Python numbers only.
    # A native STA must not load SciPy/BLAS DLLs during an accepted CAD task.
    u=[0.]*(count+1);v=[0.]*(count+1);p=[0]*(count+1);way=[0]*(count+1)
    for i in range(1,count+1):
        p[0]=i;j0=0;minimum=[float('inf')]*(count+1);used=[False]*(count+1)
        while True:
            used[j0]=True;i0=p[j0];delta=float('inf');j1=0
            for j in range(1,count+1):
                if used[j]:continue
                reduced=cost[i0-1][j-1]-u[i0]-v[j]
                if reduced<minimum[j]:minimum[j]=reduced;way[j]=j0
                if minimum[j]<delta:delta=minimum[j];j1=j
            for j in range(count+1):
                if used[j]:u[p[j]]+=delta;v[j]-=delta
                else:minimum[j]-=delta
            j0=j1
            if p[j0]==0:break
        while j0:
            j1=way[j0];p[j0]=p[j1];j0=j1
    result={names[p[j]-1]:list(anchors[j-1]) for j in range(1,count+1)}
    if crossing_count([(result[n],tips[n]) for n in names]):raise ValueError('No noncrossing leader layout found in the bounded sheet')
    return result
