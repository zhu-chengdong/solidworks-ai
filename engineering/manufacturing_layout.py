"""Bounded sheet-space leader routing; never alter measured geometry."""
import math


def free_text_coordinate(center,lower,upper,extensions):
    """Keep dimension glyphs clear of perpendicular extension lines."""
    for offset in (0.,.008,-.008,.016,-.016,.024,-.024,.032,-.032):
        candidate=center+offset
        if lower+.004<candidate<upper-.004 and all(abs(candidate-x)>.005 for x in extensions):return candidate
    raise ValueError('No clear dimension-text position fits the measured span')


def segment_distance(point,a,b):
    delta=[b[i]-a[i] for i in (0,1)];length=sum(v*v for v in delta)
    t=max(0.,min(1.,sum((point[i]-a[i])*delta[i] for i in (0,1))/length)) if length else 0.
    return math.dist(point[:2],[a[i]+t*delta[i] for i in (0,1)])


def intersects(a,b,c,d):
    def cross(p,q,r):return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    return cross(a,b,c)*cross(a,b,d)<-1e-16 and cross(c,d,a)*cross(c,d,b)<-1e-16


def overlaps(a,b):return min(a[2],b[2])-max(a[0],b[0])>1e-6 and min(a[3],b[3])-max(a[1],b[1])>1e-6


def hits_box(a,b,box):
    if any(box[0]<=p[0]<=box[2] and box[1]<=p[1]<=box[3] for p in (a,b)):return True
    p,q,r,s=[box[:2],[box[2],box[1]],box[2:],[box[0],box[3]]]
    return any(intersects(a,b,u,v) for u,v in ((p,q),(q,r),(r,s),(s,p)))


def clear_other_holes(points,own,holes,scale,margin=.0015):
    return all(segment_distance(h['sheet_center_m'],a,b)>h['radius_mm']/1000*scale+margin
        for h in holes if h is not own
        for a,b in zip(points,points[1:]))


def callout_anchor(hole,holes,outline,occupied,index,scale):
    origin=hole['sheet_center_m'][:2];right=outline[2]+.020;left=outline[0]-.030;above=outline[3]+.018
    candidates=[[right,outline[3]-.012-index*.020],[left,above],[right,above]]
    candidates += [[x,y] for y in (.278,.260,.244,.225,.185,.165,.145) for x in (right,left,.030,.250)]
    for position in candidates:
        # Reserve a conservative 65 x 14 mm region, including a two-line callout.
        box=[position[0],position[1]-.003,position[0]+.065,position[1]+.011]
        if box[0]<.028 or box[1]<.035 or box[2]>.405 or box[3]>.290 or overlaps(box,outline):continue
        if not clear_other_holes([origin,position],hole,holes,scale):continue
        if any(overlaps(box,row['box']) or intersects(origin,position,*row['line'])
               or hits_box(origin,position,row['box']) or hits_box(*row['line'],box) for row in occupied):continue
        occupied.append({'box':box,'line':[origin,position]})
        return position
    raise ValueError('No qualified non-crossing callout placement fits this sheet; create a simpler drawing revision')
