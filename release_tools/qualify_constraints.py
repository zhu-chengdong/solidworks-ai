"""Live native acceptance: no Fix; driving edit, restore, save/reopen, geometry."""
from pathlib import Path
import json, math, sys, time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    import server
    engine = server.load_server()
    output = ROOT/'artifacts'/('ConstraintAcceptance_'+time.strftime('%Y%m%d_%H%M%S'))
    output.mkdir()
    cases = [
        ('LProfile', {'family':'prism','points':[[0,0],[40,0],[40,10],[10,10],[10,30],[0,30]],'depth_mm':8,'holes':[]}),
        ('Cylinder', {'family':'revolve','points':[[0,10],[20,10]],'depth_mm':1,'holes':[]}),
        ('SteppedPlate', {'family':'prism','points':[[0,0],[80,0],[80,20],[60,20],[60,45],[45,60],[20,60],[20,40],[0,40]],
             'depth_mm':8,'holes':[{'x_mm':15,'y_mm':15,'radius_mm':3},{'x_mm':65,'y_mm':10,'radius_mm':4},{'x_mm':35,'y_mm':45,'radius_mm':5}]})]
    if sys.argv[1:]:
        cases = [(name, raw) for name, raw in cases if name in sys.argv[1:]]
    def operation():
        from integrations.czuryk.reference_build import ReferenceGeometry, build_reference
        from integrations.czuryk.native_only import native_automation
        from integrations.czuryk.dimensioned import geometry_evidence
        from scripts.sw_connect import get_com_member as get, save_document, open_document
        from scripts.sw_sketch_quality import inspect_model_sketches
        from scripts.sw_review import run_review
        from scripts.sw_document_data import update_dimension_mm as update_dimension
        app,_ = engine.connect_solidworks()
        results=[]
        for name, raw in cases:
            folder=output/name;folder.mkdir()
            spec=ReferenceGeometry(**raw)
            source=folder/'reference-spec.json';source.write_text(spec.model_dump_json(indent=2),encoding='utf-8')
            path=folder/(name+'_'+output.name.rsplit('_',1)[-1]+'.SLDPRT')
            build=build_reference(app,str(source),str(path),str(ROOT/'artifacts'))
            assert build['success'],build
            doc=app.ActiveDoc;automation=native_automation(app)
            record={'name':name,'build':build}
            if spec.family=='prism':
                dimension=doc.Parameter('D1@ReferenceExtrude')
                assert math.isclose(get(dimension,'SystemValue')*1000,spec.depth_mm,abs_tol=1e-6)
                updated=update_dimension(doc,'D1@ReferenceExtrude',spec.depth_mm+1)
                assert updated['success'],updated
                assert get(doc,'ForceRebuild3',False)
                print('DRIVING_DIMENSION '+json.dumps(updated,ensure_ascii=False),flush=True)
                changed=spec.model_copy(update={'depth_mm':spec.depth_mm+1})
                changed_evidence=geometry_evidence(automation,doc,changed)
                assert changed_evidence['passed'],changed_evidence
                assert inspect_model_sketches(doc)['status']=='pass'
                record['driving_edit']={'dimension':'D1@ReferenceExtrude','before_mm':spec.depth_mm,
                    'after_mm':spec.depth_mm+1,'geometry':changed_evidence}
                restored=update_dimension(doc,'D1@ReferenceExtrude',spec.depth_mm)
                assert get(doc,'ForceRebuild3',False)
                assert restored['success'] and save_document(doc,str(path))
            else:
                # Change the actual radius-driving sketch dimension; verify it is
                # editable through a real B-Rep volume change, then restore.
                names=build['sketch_quality']['sketches'][0]['dimension_names']
                edited=False
                for label in names:
                    dim=doc.Parameter(label)
                    value=get(dim,'SystemValue')
                    if math.isclose(value,.010,abs_tol=1e-6):
                        updated=update_dimension(doc,label,12)
                        assert updated['success'],updated
                        assert get(doc,'ForceRebuild3',False)
                        print('DRIVING_DIMENSION '+json.dumps(updated,ensure_ascii=False),flush=True)
                        changed=ReferenceGeometry(family='revolve',points=[[0,12],[20,12]],depth_mm=1)
                        ev=geometry_evidence(automation,doc,changed)
                        assert ev['passed'],ev
                        record['driving_edit']={'dimension':label,'before_mm':10,'after_mm':12,'geometry':ev}
                        restored=update_dimension(doc,label,10)
                        assert get(doc,'ForceRebuild3',False)
                        assert restored['success'] and save_document(doc,str(path))
                        edited=True;break
                assert edited,'Radius driving dimension not found'
            title=str(get(doc,'GetTitle'));app.CloseDoc(title)
            doc=open_document(app,str(path),silent=True,raise_on_error=True)
            assert doc is not None and Path(get(doc,'GetPathName')).resolve()==path.resolve()
            assert Path(get(app.ActiveDoc,'GetPathName')).resolve()==path.resolve()
            quality=inspect_model_sketches(doc)
            measured=geometry_evidence(automation,doc,spec)
            assert quality['status']=='pass' and measured['passed']
            record.update(reopened_sketch_quality=quality,reopened_geometry=measured,save_reopen_verified=True)
            step=folder/(name+'.step');assert automation.save_document(str(step))['success']
            review,report=run_review(doc,str(folder),basename=name,expected_outputs=[str(path),str(step)])
            record.update(review_checks=review['checks'],evaluation=review['evaluation'],review_report=str(report))
            results.append(record)
            (folder/'acceptance.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            print('CONSTRAINT_CASE_PASS '+name,flush=True)
            if name!='SteppedPlate':app.CloseDoc(str(get(doc,'GetTitle')))
        return {'status':'ok','computer_use':False,'cases':results}
    result=engine._run_locked(operation,engine.ResponseFormat.JSON)
    (output/'acceptance.json').write_text(result,encoding='utf-8')
    print(json.dumps({'report':str(output/'acceptance.json'),'result':json.loads(result).get('status')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
