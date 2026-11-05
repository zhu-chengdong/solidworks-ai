"""Ordinary dimensioned DXF drawings, no embedded feature/spec sidecar."""
import ezdxf


def stepped_block(path,missing_depth=False,conflict=False):
    doc=ezdxf.new('R2013',setup=['linetypes']);doc.units=4;m=doc.modelspace()
    for name in ('OUTLINE','DETAIL','NOTES','LEADERS','DIM'):doc.layers.new(name)
    doc.layers.new('HIDDEN',dxfattribs={'linetype':'DASHED'})
    def poly(points,offset=(0,0)):
        return m.add_lwpolyline([(x+offset[0],y+offset[1]) for x,y in points],close=True,dxfattribs={'layer':'OUTLINE'})
    poly([(0,0),(120,0),(120,80),(0,80)],(0,130))
    poly([(0,0),(120,0),(120,12),(100,12),(100,36),(20,36),(20,12),(0,12)])
    poly([(0,0),(80,0),(80,36),(48,36),(48,12),(0,12)],(170,0))
    for a,b in [((20,178),(100,178)),((20,178),(20,210)),((100,178),(100,210)),((20,12),(100,12))]:m.add_line(a,b,dxfattribs={'layer':'DETAIL'})
    for role,position in [('TOP',(60,118)),('FRONT',(60,-12)),('RIGHT',(210,-12))]:m.add_text(role,dxfattribs={'height':4,'insert':position,'layer':'NOTES'})
    m.add_text('THIRD ANGLE; SOLID UNLESS SHOWN; FLAT BOTTOM BLIND HOLES',dxfattribs={'height':3,'insert':(-125,255),'layer':'NOTES'})
    holes=[('H1',(34,64),[4],('H1 DIA8 BLIND' if missing_depth else 'H1 DIA8 BLIND DEPTH12'),(-125,216)),
           ('H2',(60,64),[3.3,6.5],'H2 DIA6.6 THRU CBORE DIA13 DEPTH5',(0,237)),
           ('H3',(86,64),[4,7],'H3 DIA8 BLIND DEPTH20 CBORE DIA14 DEPTH6',(100,225)),
           ('H4',(40,20),[3],'H4 DIA6 BLIND DEPTH7',(-125,160)),
           ('H5',(90,20),[3.3],'H5 DIA6.6 THRU',(105,112))]
    for hid,(x,y),radii,note,position in holes:
        for radius in radii:m.add_circle((x,y+130),radius,dxfattribs={'layer':'OUTLINE'})
        m.add_leader([(x,y+130),position],dxfattribs={'layer':'LEADERS'})
        m.add_text(note,dxfattribs={'height':3,'insert':position,'layer':'NOTES'})
    for x,r,bottom,top in [(34,4,24,36),(60,3.3,0,36),(60,6.5,31,36),(86,4,16,36),(86,7,30,36),(40,3,5,12),(90,3.3,0,12)]:
        for a,b in [((x-r,bottom),(x-r,top)),((x+r,bottom),(x+r,top)),((x-r,bottom),(x+r,bottom))]:m.add_line(a,b,dxfattribs={'layer':'HIDDEN'})
    m.add_text('TOP DATUM: LOWER LEFT (0,0), mm',dxfattribs={'height':3,'insert':(170,190),'layer':'NOTES'})
    for i,line in enumerate(['H1 (34,64)','H2 (60,64)','H3 (86,64)','H4 (40,20)','H5 (90,20)']):m.add_text(line,dxfattribs={'height':3,'insert':(170,183-i*6),'layer':'NOTES'})
    for base,a,b,angle in [((0,-25),(0,0),(120,0),0),((150,0),(120,0),(120,36),90),((140,130),(120,130),(120,210),90),((20,48),(20,36),(100,36),0),((-15,0),(0,0),(0,12),90),((218,49),(218,36),(250,36),0)]:
        dim=m.add_linear_dim(base=base,p1=a,p2=b,angle=angle,dxfattribs={'layer':'DIM'})
        if conflict and angle==0:dim.dimension.dxf.text='125'
        dim.render()
    if path is not None:doc.saveas(path)
    return doc


def blind_plate(path):
    import math
    doc=ezdxf.new('R2013');doc.units=4;m=doc.modelspace();b=math.tan(math.pi/8)
    m.add_lwpolyline([(-42,-35,0),(42,-35,b),(50,-27,0),(50,27,b),(42,35,0),(-42,35,b),(-50,27,0),(-50,-27,b)],format='xyb',close=True)
    m.add_text('FLAT BOTTOM BLIND HOLES',dxfattribs={'height':3,'insert':(-50,65)})
    for center,radii,text,tail in [((-22,0),[5],'H1 DIA10 BLIND DEPTH8',(-85,48)),((22,0),[3.3,6],'H2 DIA6.6 THRU CBORE DIA12 DEPTH4',(30,48))]:
        for radius in radii:m.add_circle(center,radius)
        m.add_leader([center,tail]);m.add_text(text,dxfattribs={'height':3,'insert':tail})
    if path is not None:doc.saveas(path)
    return doc


def analytic_housing(path,curved=False,missing_angle=False,total_depth=False):
    """Dimensioned, ordinary three-view DXF with axis and bottom conventions."""
    import math
    doc=ezdxf.new('R2013',setup=['linetypes']);doc.units=4;m=doc.modelspace()
    for name in ('OUTLINE','DETAIL','NOTES','LEADERS','DIM'):doc.layers.new(name)
    doc.layers.new('HIDDEN',dxfattribs={'linetype':'DASHED'})
    L,W,H=(100,60,60) if curved else (120,80,50);top=(0,130);right=(L+60,0)
    def poly(points,offset=(0,0)):
        m.add_lwpolyline([(x+offset[0],y+offset[1]) for x,y in points],close=True,dxfattribs={'layer':'OUTLINE'})
    poly([(0,0),(L,0),(L,W),(0,W)],top);poly([(0,0),(W,0),(W,H),(0,H)],right)
    if curved:
        m.add_lwpolyline([(0,0,0),(100,0,0),(100,10,1),(0,10,0)],format='xyb',close=True,dxfattribs={'layer':'OUTLINE'})
    else:poly([(0,0),(120,0),(120,50),(60,50),(0,30)])
    for role,position in [('TOP',(L/2,118)),('FRONT',(L/2,-12)),('RIGHT',(right[0]+W/2,-12))]:m.add_text(role,dxfattribs={'height':4,'insert':position,'layer':'NOTES'})
    m.add_text('THIRD ANGLE; SOLID UNLESS SHOWN; mm',dxfattribs={'height':3,'insert':(-120,245),'layer':'NOTES'})
    if curved:
        holes=[('front',(25,15),[4],'H1 DIA8 BLIND TOTAL DEPTH20 POINT118',(-130,74)),('front',(75,18),[3.3,6.5],'H2 DIA6.6 THRU CSK DIA13 ANGLE90',(95,92)),('front',(50,38),[3,5],'H3 DIA6 BLIND DEPTH12 FLAT BOTTOM CBORE DIA10 DEPTH4',(20,106))]
    else:
        holes=[('front',(22,14),[4],'H1 DIA8 BLIND '+('TOTAL' if total_depth else 'CYL')+' DEPTH18 POINT118',(-135,74)),('top',(90,28),[3.3,6.5],'H2 DIA6.6 THRU CSK DIA13'+('' if missing_angle else ' ANGLE90'),(5,238)),('right',(56,18),[3.3,6.5],'H3 DIA6.6 THRU CSK DIA13 ANGLE82',(185,100)),('top',(90,62),[4],'H4 DIA8 BLIND CYL DEPTH12 POINT118',(80,220))]
    for role,center,radii,text,tail in holes:
        offset=top if role=='top' else right if role=='right' else (0,0);p=(center[0]+offset[0],center[1]+offset[1])
        for r in radii:m.add_circle(p,r,dxfattribs={'layer':'OUTLINE'})
        m.add_leader([p,tail],dxfattribs={'layer':'LEADERS'});m.add_text(text,dxfattribs={'height':3,'insert':tail,'layer':'NOTES'})
    # Ordinary hidden-line projections provide an independent check on hole
    # depth, drill apex and countersink taper; they are not feature metadata.
    tip=4/math.tan(math.radians(59));cylinder=(20 if curved else 18)-tip if curved or total_depth else 18;cx=25 if curved else 22
    hidden=[]
    for sign in (-1,1):
        hidden.extend([((cx+sign*4,130),(cx+sign*4,130+cylinder)),((cx+sign*4,130+cylinder),(cx,130+cylinder+tip))])
        if not curved:
            hidden.extend([((90+sign*4,50),(90+sign*4,38)),((90+sign*4,38),(90,38-tip))])
            recess=(6.5-3.3)/math.tan(math.radians(41))
            hidden.extend([((120,130+56+sign*6.5),(120-recess,130+56+sign*3.3)),((120-recess,130+56+sign*3.3),(0,130+56+sign*3.3))])
    for p,q in hidden:m.add_line(p,q,dxfattribs={'layer':'HIDDEN'})
    # Real dimensions and hole positions remain visible in a regular CAD viewer.
    for base,a,b,angle in [((0,-28),(0,0),(L,0),0),((L+20,0),(L,0),(L,H),90),((L+18,130),(L,130),(L,130+W),90)]:m.add_linear_dim(base=base,p1=a,p2=b,angle=angle,dxfattribs={'layer':'DIM'}).render()
    if curved:m.add_radius_dim(center=(50,10),radius=50,angle=55,dxfattribs={'layer':'DIM'}).render()
    else:m.add_text('SLOPE: (0,30) TO (60,50); FLAT ROOF X60..120',dxfattribs={'height':3,'insert':(-120,256),'layer':'NOTES'})
    if path is not None:doc.saveas(path)
    return doc
