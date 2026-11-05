import math
import ezdxf


def plate(path,multi=False,unit=4,conflict=False):
    d=ezdxf.new('R2013');d.units=unit;m=d.modelspace()
    b=math.tan(math.pi/8)
    m.add_lwpolyline([(-50,-40,0),(50,-40,b),(60,-30,0),(60,30,b),(50,40,0),(-50,40,b),(-60,30,0),(-60,-30,b)],format='xyb',close=True)
    for x in (-42,42):
        for y in (-24,24):m.add_circle((x,y),4)
    m.add_lwpolyline([(-9,-6,0),(9,-6,1),(9,6,0),(-9,6,1)],format='xyb',close=True)
    d.layers.new('DIM')
    dim=m.add_linear_dim(base=(0,-55),p1=(-60,-30),p2=(60,-30),angle=0,dxfattribs={'layer':'DIM'})
    if conflict:dim.dimension.dxf.text='125'
    dim.render()
    if multi:
        m.add_lwpolyline([(-60,65),(60,65),(60,73),(-60,73)],close=True)
        m.add_lwpolyline([(85,-40),(93,-40),(93,40),(85,40)],close=True)
    d.saveas(path)
    return d
