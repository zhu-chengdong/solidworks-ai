"""Dimensioned, original fixture image; an image input, not a prebuilt CAD model."""
from PIL import Image, ImageDraw, ImageFont


def stepped_plate_image(path):
    image=Image.new('RGB',(1920,1240),'white');d=ImageDraw.Draw(image)
    font=ImageFont.truetype('arial.ttf',26)
    title=ImageFont.truetype('arialbd.ttf',38)
    small=ImageFont.truetype('arial.ttf',23)
    d.text((75,45),'STEPPED MOUNTING PLATE - DIMENSIONED TEST REFERENCE',font=title,fill='#172334')
    d.text((75,108),'Front view | Units: mm | Constant thickness: 8 | Sharp edges | 3 THROUGH HOLES',font=font,fill='#253b54')
    points=[(0,0),(80,0),(80,20),(60,20),(60,45),(45,60),(20,60),(20,40),(0,40)]
    def xy(x,y):return (150+x*10,900-y*10)
    d.polygon([xy(x,y) for x,y in points],fill='#e8eff5',outline='#152334',width=4)
    offsets=[(-28,12),(12,12),(12,-24),(14,12),(16,-22),(0,-34),(-35,-34),(-35,-22),(-30,-24)]
    for name,(x,y),(dx,dy) in zip('ABCDEFGHI',points,offsets):
        p=xy(x,y);d.text((p[0]+dx,p[1]+dy),name,font=font,fill='black')
    for label,x,y,r in [('H1',15,15,3),('H2',65,10,4),('H3',35,45,5)]:
        cx,cy=xy(x,y);rr=r*10
        d.ellipse((cx-rr,cy-rr,cx+rr,cy+rr),fill='white',outline='black',width=3)
        d.line((cx-rr-12,cy,cx+rr+12,cy),fill='#768698',width=1)
        d.line((cx,cy-rr-12,cx,cy+rr+12),fill='#768698',width=1)
        d.text((cx+rr+12,cy-15),label,font=small,fill='#152334')
    # Overall dimensions, with true parallel projection and independent origin.
    d.line((150,985,950,985),fill='black',width=2)
    for x in (150,950):
        d.line((x,930,x,1002),fill='#536172',width=2)
        d.line((x-8,993,x+8,977),fill='black',width=2)
    d.text((510,995),'80',font=font,fill='black')
    d.line((75,900,75,300),fill='black',width=2)
    for y in (900,300):
        d.line((60,y,130,y),fill='#536172',width=2)
        d.line((67,y+8,83,y-8),fill='black',width=2)
    d.text((24,580),'60',font=font,fill='black')
    d.text((145,1080),'Origin A = (0, 0). +X right; +Y up.',font=font,fill='#253b54')
    d.text((1080,215),'OUTLINE VERTICES (connect A to I, then A)',font=font,fill='#172334')
    d.text((1100,265),'Vertex       X          Y',font=font,fill='black')
    for i,(name,(x,y)) in enumerate(zip('ABCDEFGHI',points)):
        y0=310+i*41;d.text((1100,y0),name,font=font,fill='black')
        d.text((1285,y0),str(x),font=font,fill='black');d.text((1440,y0),str(y),font=font,fill='black')
    d.text((1080,715),'THROUGH HOLES',font=font,fill='#172334')
    d.text((1100,762),'Hole         X          Y         Diameter',font=font,fill='black')
    for i,(label,x,y,diameter) in enumerate([('H1',15,15,6),('H2',65,10,8),('H3',35,45,10)]):
        y0=810+i*46
        for xx,value in zip((1100,1285,1440,1580),(label,x,y,diameter)):
            d.text((xx,y0),str(value),font=font,fill='black')
    d.text((1080,1000),'Thickness: 8 mm',font=font,fill='black')
    d.text((75,1170),'Original software acceptance fixture. This reference is created independently of the CAD output.',font=small,fill='#596779')
    image.save(path)
