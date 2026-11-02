"""Native 2024 mixed-part assembly qualification. Never replay a failed stage."""
import hashlib,json,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    import server
    from engineering.spec import DesignSpec
    from engineering.native import execute_stage
    spec=DesignSpec.model_validate_json((ROOT/'engineering/examples/bracket_shaft_plate.json').read_text(encoding='utf-8'))
    out=ROOT/'artifacts'/('MixedAssembly_'+time.strftime('%Y%m%d_%H%M%S'));out.mkdir()
    source=out/'design-spec.json';source.write_text(spec.model_dump_json(indent=2),encoding='utf-8')
    engine=server.load_server()
    for index,stage in enumerate(spec.stages()):
        def op():
            try:
                app,_=engine.connect_solidworks();return execute_stage(app,str(source),str(out),index,str(ROOT/'artifacts'))
            except BaseException:traceback.print_exc();raise
        result=json.loads(engine._run_locked(op,engine.ResponseFormat.JSON))
        print(json.dumps({'stage':index,'label':stage['label'],'status':result.get('status'),'error':result.get('message')},ensure_ascii=False),flush=True)
        if not result.get('success'):
            (out/'failure.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');raise SystemExit(1)
    record=json.loads((out/'design-acceptance.json').read_text(encoding='utf-8'))
    assert record['status']=='passed',record['verification']
    assert record['verification']['component_count']==7 and record['verification']['mate_readback']['passed']
    assert record['verification']['interference']['interference_count']==0 and record['verification']['step_reimport']['reimported_body_count']==7
    from PIL import Image
    for path in out.glob('*.bmp'):
        with Image.open(path) as image:image.save(path.with_suffix('.png'))
    print('MIXED_ASSEMBLY_PASS '+str(out),flush=True)


if __name__=='__main__':main()
