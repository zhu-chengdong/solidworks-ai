import asyncio
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.czuryk.reference_build import ReferenceGeometry, build_reference
from workbench.engine import WorkbenchEngine, ReferencePlan, image_input
from workbench.jobs import Job, JobManager
from workbench.modules import Module, ModuleRegistry
from workbench.reference_inputs import ReferenceStore, pin_references
from workbench.settings import UserFacingError
from workbench_support import configured_store, FakeMCP, ScriptedAPI


def picture():
    data = io.BytesIO()
    Image.new('RGB', (80, 60), 'white').save(data, 'PNG')
    return data.getvalue()


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ReferenceStore(self.root/'uploads')

    def tearDown(self):
        self.temp.cleanup()

    def test_upload_is_normalized_hashed_and_pinned_separately_from_outputs(self):
        ref = self.store.add(picture(), '../../参考.png')
        self.assertEqual(ref['name'], '参考.png')
        job = Job('按图建模', self.root/'jobs')
        pin_references(job, self.store.resolve([ref['id']]))
        job.collect_artifacts()
        self.assertEqual(job.artifacts, [])
        self.assertEqual(len(image_input(job, '要求')[0]['content']), 3)
        self.assertTrue((job.output_dir/job.references[0]['file']).is_file())
        (self.store.root/(ref['id']+'.png')).write_bytes(b'changed')
        with self.assertRaises(UserFacingError):
            self.store.get(ref['id'])

    def test_invalid_images_and_paths_are_rejected(self):
        for raw in (b'not an image', b'', b'x'*(8*1024*1024+1)):
            with self.assertRaises(UserFacingError):
                self.store.add(raw, 'bad.png')
        with self.assertRaises(UserFacingError):
            self.store.get('../../settings')

    def test_geometry_rejects_self_intersections_nonfinite_and_invalid_rotation(self):
        for data in (
            dict(family='prism', points=[[0,0],[10,10],[10,0],[0,10]],depth_mm=8),
            dict(family='prism', points=[[0,0],[float('nan'),0],[0,10]],depth_mm=8),
            dict(family='revolve',points=[[0,10],[0,20]],depth_mm=1)):
            with self.assertRaises(ValueError):
                ReferenceGeometry(**data)

    def test_prism_volume_and_program_have_no_model_supplied_code(self):
        spec=ReferenceGeometry(family='prism',points=[[0,0],[40,0],[40,10],[10,10],[10,30],[0,30]],depth_mm=8)
        self.assertEqual(spec.expected_volume(),4800)
        self.assertIn("model.prism('ReferencePart'",spec.program())
        with self.assertRaises(ValueError):
            ReferenceGeometry(family='prism',points=[[0,0],[1,0],[0,1]],depth_mm=8,code='import os')

    def test_native_tool_rejects_external_spec_before_touching_com(self):
        with self.assertRaises(ValueError):
            build_reference(None,str(self.root/'outside.json'),str(self.root/'jobs/model.SLDPRT'),str(self.root/'jobs'))

    def test_hole_validation_rejects_touching_boundary_overlap_and_revolve_holes(self):
        base=dict(family='prism',points=[[0,0],[40,0],[40,30],[0,30]],depth_mm=8)
        for holes in ([{'x_mm':1,'y_mm':10,'radius_mm':2}],
                      [{'x_mm':10,'y_mm':10,'radius_mm':3},{'x_mm':15,'y_mm':10,'radius_mm':3}],
                      [{'x_mm':float('nan'),'y_mm':10,'radius_mm':3}]):
            with self.assertRaises(ValueError):ReferenceGeometry(**base,holes=holes)
        with self.assertRaises(ValueError):
            ReferenceGeometry(family='revolve',points=[[0,10],[20,10]],depth_mm=1,
                holes=[{'x_mm':10,'y_mm':10,'radius_mm':2}])

    def test_through_hole_volume_and_legacy_program_cannot_silently_omit_holes(self):
        import math
        spec=ReferenceGeometry(family='prism',points=[[0,0],[40,0],[40,30],[0,30]],depth_mm=8,
            holes=[{'x_mm':10,'y_mm':10,'radius_mm':3}])
        self.assertAlmostEqual(spec.expected_volume(),(1200-math.pi*9)*8)
        with self.assertRaises(ValueError):spec.program()

    def test_review_finds_step_beside_native_part_when_previews_are_in_subdirectory(self):
        from integrations.czuryk.review_outputs import expected_outputs
        directory=self.root/'job';directory.mkdir();(directory/'review').mkdir()
        native=directory/'model.SLDPRT';native.write_bytes(b'native fixture')
        step=directory/'model.step';step.write_bytes(b'step fixture')
        paths=expected_outputs(native,directory/'review',self.root)
        self.assertEqual(paths,[str(native),str(step)])
        self.assertTrue(all(Path(p).is_file() for p in paths))

    def test_weak_executor_cannot_change_agreed_geometry_or_path(self):
        job=Job('建模',self.root/'jobs')
        pin_references(job,self.store.resolve([self.store.add(picture(),'ref.png')['id']]))
        spec=ReferenceGeometry(family='prism',points=[[0,0],[10,0],[0,10]],depth_mm=8)
        plan=ReferencePlan(summary='三角形',action='create',needs_clarification=False,supported=True,
            questions=[],steps=[],checks=[],geometry=spec,observations=[],assumptions=[])
        path=job.output_dir/'reference-spec.json'
        path.write_text(spec.model_dump_json())
        args={'params':{'spec_path':str(path),'output_path':str(job.output_dir/('model_'+job.id+'.SLDPRT'))}}
        WorkbenchEngine.guard_arguments(job,plan,'solidworks_build_reference',args)
        path.write_text('{}')
        with self.assertRaises(UserFacingError):
            WorkbenchEngine.guard_arguments(job,plan,'solidworks_build_reference',args)

    def test_module_registry_routes_by_module_and_rejects_missing(self):
        engine=object()
        registry=ModuleRegistry([Module('test','测试',('text',),engine)])
        self.assertIs(registry.require('test').engine,engine)
        with self.assertRaises(UserFacingError):
            registry.require('missing')

    def test_nonvision_model_rejected_before_job_or_cad(self):
        settings=configured_store(self.root)
        config=settings.read();config['roles']['planner']['vision']=False;settings.save(config)
        manager=JobManager(WorkbenchEngine(settings),self.root/'jobs')
        try:
            refs=self.store.resolve([self.store.add(picture(),'ref.png')['id']])
            with self.assertRaises(UserFacingError):
                manager.submit('建模',references=refs)
            self.assertFalse(manager.jobs)
        finally:
            manager.pool.shutdown()


class ReferencePlanningTests(unittest.IsolatedAsyncioTestCase):
    async def test_reference_missing_dimensions_clarifies_and_does_not_start_weak_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);settings=configured_store(root);mcp=FakeMCP()
            class API(ScriptedAPI):
                def handle(self,request):
                    import httpx2
                    body=json.loads(request.content)
                    self.requests.append(body)
                    output=self.message(json.dumps(dict(summary='缺少厚度',action='create',needs_clarification=True,
                        supported=True,questions=['厚度是多少？'],steps=[],checks=[],geometry=None,observations=['L轮廓'],assumptions=[])))
                    return httpx2.Response(200,json={'id':'resp_image','object':'response','created_at':1700000000,
                        'model':body['model'],'status':'completed','output':output,
                        'usage':{'input_tokens':20,'output_tokens':20,'total_tokens':40}})
            api=API();job=Job('按图建模',root/'jobs');store=ReferenceStore(root/'uploads')
            pin_references(job,store.resolve([store.add(picture(),'ref.png')['id']]))
            await WorkbenchEngine(settings,mcp.session,api.model).run(job)
            self.assertEqual(job.phase,'clarify')
            self.assertEqual(len(api.requests),1)
            self.assertIn('input_image',json.dumps(api.requests[0]))
            self.assertFalse(any('create' in name or 'build' in name for name,_ in mcp.calls))
