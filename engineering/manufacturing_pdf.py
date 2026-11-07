"""Inspect the actual native-exported PDF with the bundled PDFium backend."""
from pathlib import Path
import hashlib, math, re
import pypdfium2 as pdfium

POINTS_PER_M=72/.0254


def text_boxes(page):
    result=[]
    text=page.get_textpage()
    try:
        for index in range(text.count_chars()):
            char=text.get_text_range(index,1)
            if not char or char.isspace():continue
            box=list(text.get_charbox(index))
            if all(math.isfinite(v) for v in box) and box[2]>box[0] and box[3]>box[1]:
                result.append({'char':char,'index':index,'box_pt':box})
        return text.get_text_range(),result
    finally:text.close()


def numeric_runs(chars):
    groups=[];current=[]
    for item in chars:
        if re.fullmatch(r'[0-9.+-]',item['char']):
            if current and item['index']>current[-1]['index']+1:
                groups.append(current);current=[]
            current.append(item)
        elif current:groups.append(current);current=[]
    if current:groups.append(current)
    result=[]
    for group in groups:
        try:value=float(''.join(c['char'] for c in group))
        except ValueError:continue
        result.append({'text':''.join(c['char'] for c in group),'value':value,
            'box_pt':[min(c['box_pt'][0] for c in group),min(c['box_pt'][1] for c in group),max(c['box_pt'][2] for c in group),max(c['box_pt'][3] for c in group)],
            'indices':[c['index'] for c in group]})
    return result


def distance_to_box(point,box):
    return math.hypot(max(box[0]-point[0],0,point[0]-box[2]),max(box[1]-point[1],0,point[1]-box[3]))


def inspect_pdf(path,dimensions,preview_path):
    path=Path(path);document=pdfium.PdfDocument(path);matches=[]
    try:
        if len(document)!=1:raise ValueError('The drawing must export exactly one PDF sheet')
        page=document[0]
        width,height=page.get_size()
        if abs(width/POINTS_PER_M-.420)>.0001 or abs(height/POINTS_PER_M-.297)>.0001:
            raise ValueError('Native PDF paper size does not match A3 landscape')
        text,chars=text_boxes(page);runs=numeric_runs(chars)
        outside=[c for c in chars if c['box_pt'][0]<0 or c['box_pt'][1]<0 or c['box_pt'][2]>width+.5 or c['box_pt'][3]>height+.5]
        if outside:raise ValueError('PDF text is clipped outside the drawing sheet')
        used=set()
        for item in dimensions:
            point=[v*POINTS_PER_M for v in item['position_m'][:2]]
            formatted=re.sub(r'<[^>]+>',' ',''.join(item.get('text_parts',[])))
            values=[float(v) for v in re.findall(r'\d+(?:\.\d+)?',formatted)] if item['is_hole_callout'] else [item['value_m']*1000]
            if not values:raise ValueError('Native hole callout has no readable formatted specification: '+item['id'])
            spans=[]
            for expected in values:
                candidates=[(distance_to_box(point,r['box_pt']),index,r) for index,r in enumerate(runs)
                    if index not in used and math.isclose(abs(r['value']) if item['is_hole_callout'] else r['value'],expected,abs_tol=.015)]
                candidates.sort(key=lambda row:row[0])
                if not candidates or candidates[0][0]>(.035 if item['is_hole_callout'] else .018)*POINTS_PER_M:
                    raise ValueError('Native annotation has no matching actual PDF value near its anchor: '+item['id']+' '+str(expected))
                distance,index,match=candidates[0];used.add(index)
                spans.append({'expected_value':expected,'pdf_text':match['text'],'box_pt':match['box_pt'],
                    'anchor_distance_mm':distance/POINTS_PER_M*1000})
            matches.append({'id':item['id'],'native_dimension':item['name'],'expected_mm':expected,
                'pdf_text':spans[0]['pdf_text'],'box_pt':spans[0]['box_pt'],'formatted_native_text':formatted,
                'spans':spans,'is_hole_callout':item['is_hole_callout'],
                'evidence_source':'actual_native_export_pdf_character_boxes'})
        overlaps=[]
        for i,a in enumerate(matches):
            for b in matches[i+1:]:
                for sa in a['spans']:
                    for sb in b['spans']:
                        x1,y1,x2,y2=sa['box_pt'];p1,q1,p2,q2=sb['box_pt']
                        if min(x2,p2)-max(x1,p1)>.2 and min(y2,q2)-max(y1,q1)>.2:overlaps.append([a['id'],b['id']])
        if overlaps:raise ValueError('Actual PDF dimension text overlaps: '+str(overlaps))
        bitmap=page.render(scale=2.2)
        try:
            picture=bitmap.to_pil();picture.save(preview_path);picture.close()
        finally:bitmap.close()
        return {'passed':True,'pdf_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'page_count':1,'paper_mm':[width/POINTS_PER_M*1000,height/POINTS_PER_M*1000],
            'dimension_matches':matches,'matched_dimension_count':len(matches),'clipped_characters':len(outside),
            'dimension_text_overlaps':overlaps,'text':text,'parser':'PDFium','preview_sha256':hashlib.sha256(Path(preview_path).read_bytes()).hexdigest(),
            'scope':'Actual PDF text matching and dimension-text collisions; visual review also checks lines, leaders and hatching.'}
    finally:document.close()
