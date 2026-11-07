"""Match actual native PDF cells and balloon numbers to native associations."""
import math,re
from pathlib import Path
import pypdfium2 as pdfium
from .manufacturing import digest
from .manufacturing_pdf import text_boxes,numeric_runs,distance_to_box,POINTS_PER_M

def compact(value):return re.sub(r'\s+','',str(value))

def inspect_pdf(path,bom,balloons,preview,view_labels=()):
    document=pdfium.PdfDocument(path)
    try:
        if len(document)!=1:raise ValueError('Assembly drawing requires one actual PDF page')
        page=document[0];width,height=page.get_size()
        if abs(width/POINTS_PER_M-.420)>.0001 or abs(height/POINTS_PER_M-.297)>.0001:raise ValueError('Assembly PDF is not A3 landscape')
        text,chars=text_boxes(page)
        outside=[c for c in chars if c['box_pt'][0]<0 or c['box_pt'][1]<0 or c['box_pt'][2]>width+.5 or c['box_pt'][3]>height+.5]
        if outside:raise ValueError('Actual assembly PDF contains clipped text')
        for label in view_labels:
            if compact(label['text']) not in compact(text):raise ValueError('Native view label is missing from the actual PDF')
        origin=bom['position_m'];cells=[];y=origin[1]
        for row_index,row in enumerate([bom['headers']]+[r['cells'] for r in bom['rows']]):
            x=origin[0];bottom=y-bom['row_heights_m'][row_index]
            for col,expected in enumerate(row):
                right=x+bom['column_widths_m'][col]
                candidates=[c for c in chars if x*POINTS_PER_M-.5<=(c['box_pt'][0]+c['box_pt'][2])/2<=right*POINTS_PER_M+.5 and bottom*POINTS_PER_M-.5<=(c['box_pt'][1]+c['box_pt'][3])/2<=y*POINTS_PER_M+.5]
                actual=''.join(c['char'] for c in candidates)
                if compact(actual)!=compact(expected):raise ValueError('Native BOM cell differs from actual PDF: '+str((row_index,col,expected,actual)))
                cells.append({'row':row_index,'column':col,'text':actual,'box_pt':[x*POINTS_PER_M,bottom*POINTS_PER_M,right*POINTS_PER_M,y*POINTS_PER_M]})
                x=right
            y=bottom
        runs=numeric_runs(chars);used=set();matches=[]
        for b in balloons:
            point=[v*POINTS_PER_M for v in b['position_m'][:2]]
            candidates=sorted((distance_to_box(point,r['box_pt']),i,r) for i,r in enumerate(runs) if i not in used and r['text']==b['item'])
            if not candidates or candidates[0][0]>.008*POINTS_PER_M:raise ValueError('Native BOM balloon number is missing near its PDF anchor: '+b['component'])
            _,index,run=candidates[0];used.add(index)
            matches.append({'component':b['component'],'item':b['item'],'pdf_text':run['text'],'box_pt':run['box_pt']})
        bitmap=page.render(scale=2.2)
        try:
            picture=bitmap.to_pil();picture.save(preview);picture.close()
        finally:bitmap.close()
        return {'passed':True,'page_count':1,'paper_mm':[420,297],'bom_cell_matches':cells,'matched_bom_rows':len(bom['rows']),
            'balloon_matches':matches,'matched_balloon_count':len(matches),'clipped_characters':0,
            'pdf_sha256':digest(path),'preview_sha256':digest(preview),'text':text,'parser':'PDFium',
            'scope':'Actual PDF BOM cell text and per-instance item numbers; native checks establish associations and visual review checks leaders.'}
    finally:document.close()
