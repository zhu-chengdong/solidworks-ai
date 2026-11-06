import base64,hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from engineering.previews import view_specs,validate_camera,active_preview_entries,ensure_active_document,reserve_preview_repair

class PreviewFrameTests(unittest.TestCase):
    def test_rechecking_corrected_source_uses_next_generation_once_per_new_task(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);old=root/'previews/round-1';old.mkdir(parents=True)
            (old/'front.png').write_bytes(b'preserve')
            (root/'CAD_delivery_preview_r3.zip').write_bytes(b'preserve-zip')
            self.assertEqual(reserve_preview_repair(root),4)
            with self.assertRaisesRegex(ValueError,'already attempted'):reserve_preview_repair(root)
            self.assertEqual((old/'front.png').read_bytes(),b'preserve')
            self.assertEqual((root/'CAD_delivery_preview_r3.zip').read_bytes(),b'preserve-zip')

    def test_failed_attempt_is_not_replayed_even_without_exported_images(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.assertEqual(reserve_preview_repair(root),1)
            with self.assertRaisesRegex(ValueError,'already attempted'):reserve_preview_repair(root)

    def test_opening_a_document_is_not_assumed_to_activate_it(self):
        old=SimpleNamespace(path='/old.SLDASM');target=SimpleNamespace(path='/target.SLDASM');app=SimpleNamespace(ActiveDoc=old);calls=[]
        def activate(app,doc):calls.append(doc.path);app.ActiveDoc=doc
        ensure_active_document(app,target,lambda doc,name:doc.path,activate)
        self.assertEqual(calls,[target.path]);self.assertIs(app.ActiveDoc,target)

    def test_failed_activation_cannot_export_a_different_document(self):
        app=SimpleNamespace(ActiveDoc=SimpleNamespace(path='/wrong.SLDASM'))
        with self.assertRaises(RuntimeError):ensure_active_document(app,SimpleNamespace(path='/target.SLDASM'),lambda doc,name:doc.path,lambda app,doc:None)

    def test_equivalent_z_up_and_y_up_preserve_front_height_and_top_normal(self):
        identity=[1,0,0,0,1,0,0,0,1]
        y_up=[1,0,0,0,0,-1,0,1,0]
        old=view_specs(identity);new=view_specs(y_up)
        self.assertEqual(new['front']['up'],[0,1,0])
        self.assertEqual(new['front']['direction'],[0,0,-1])
        self.assertEqual(new['top']['direction'],[0,-1,0])
        self.assertEqual(old['right']['direction'],[-1,0,0])
        self.assertEqual(new['right']['label'],'右视图')
        self.assertEqual(set(new),{'front','top','right','isometric'})

    def test_orientation_readback_rejects_wrong_camera_instead_of_trusting_setter(self):
        spec=view_specs([1,0,0,0,0,-1,0,1,0])['front']
        self.assertFalse(validate_camera(spec,{'right':[1,0,0],'up':[0,0,1],'toward_viewer':[0,-1,0]}))
        self.assertTrue(validate_camera(spec,{'right':[1,0,0],'up':[0,1,0],'toward_viewer':[0,0,1]}))

    def test_reflected_or_nonorthogonal_frame_cannot_produce_verified_views(self):
        for frame in ([1,0,0,0,1,0,0,0,-1],[1,0,0,1,1,0,0,0,1]):
            with self.assertRaises(ValueError):view_specs(frame)

    def test_manifest_never_promotes_stale_images_or_path_escapes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'scene_front.png').write_bytes(b'legacy')
            self.assertIsNone(active_preview_entries(root))
            (root/'preview-manifest.json').write_text(json.dumps({'passed':True,'views':[{'file':'../escape.png'}]}))
            with self.assertRaises(ValueError):active_preview_entries(root)

from unittest.mock import patch
import httpx2
from openai import AsyncOpenAI
from workbench.engine import WorkbenchEngine,EngineeringPlan,JobStopped
from workbench.jobs import Job
from workbench.preview_review import review_delivery
from workbench_support import configured_store,ScriptedAPI

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')

class PreviewCloneTests(unittest.TestCase):
    def test_invalid_source_is_rejected_before_creating_a_queued_task(self):
        from workbench.preview_review import clone_for_preview_review
        from workbench.settings import UserFacingError
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';source.mkdir()
            native=source/'model.SLDPRT';native.write_bytes(b'original')
            plan=EngineeringPlan(summary='fixture',action='create',needs_clarification=False,supported=True,questions=[],steps=[],checks=[],
                design={'document':'part','parts':[{'id':'plate','shape':'plate','length_mm':20,'width_mm':20,'thickness_mm':4}]})
            record={'verification':{'passed':True},'active_path':str(native),'package_hashes':{'model.SLDPRT':'changed'}}
            (source/'design-acceptance.json').write_text(json.dumps(record),encoding='utf-8')
            before=set(root.iterdir())
            with self.assertRaises(UserFacingError):clone_for_preview_review({'phase':'review_required','output_dir':str(source),'plan':plan.model_dump(),'id':'fixture','requests':['test']},root)
            self.assertEqual(set(root.iterdir()),before)
def manifest(root,generation):
    from engineering.previews import LABELS
    views=[]
    for key,label in LABELS.items():
        path=root/'previews'/f'round-{generation}'/(key+'.png');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(PNG)
        views.append({'id':key,'label':label,'file':path.relative_to(root).as_posix(),'sha256':hashlib.sha256(PNG).hexdigest(),'camera_verified':True})
    (root/'preview-manifest.json').write_text(json.dumps({'passed':True,'views':views}),encoding='utf-8')

class RepairAPI(ScriptedAPI):
    def __init__(self,job,still_bad=False,other_issue=False,cancel=False):
        super().__init__();self.job=job;self.reviews=0;self.still_bad=still_bad;self.other_issue=other_issue;self.cancel=cancel
    def handle(self,request):
        body=json.loads(request.content);result=super().handle(request).json()
        properties=body.get('text',{}).get('format',{}).get('schema',{}).get('properties',{})
        if 'passed' in properties:
            self.reviews+=1;bad=self.other_issue or self.reviews==1 or self.still_bad
            result['output']=self.message(json.dumps({'passed':not bad,'summary':'测试复核','issues':['孔径错误' if self.other_issue else '视图标识错误'] if bad else [],
                'preview_issues':[] if self.other_issue or not bad else ['orientation','labels']}))
            if self.cancel:self.job.cancel.set()
        elif body.get('tools'):
            if any(i.get('type')=='function_call_output' for i in body.get('input',[]) if isinstance(i,dict)):result['output']=self.message('原生预览修正已执行。')
            else:result['output']=[{'id':'fix_fc','type':'function_call','call_id':'fix_call','name':'solidworks_repair_design_previews','arguments':'{}','status':'completed'}]
        return httpx2.Response(200,json=result)

class RepairSession:
    def __init__(self,job,fail=False):self.job=job;self.calls=[];self.fail=fail
    async def call_tool(self,name,args):
        self.calls.append((name,args))
        if not self.fail:manifest(self.job.output_dir,1)
        data={'status':'failed' if self.fail else 'passed','success':not self.fail,'native_files_unchanged':not self.fail,'package_verified':not self.fail}
        return SimpleNamespace(isError=self.fail,structuredContent=data,content=[])

class PreviewRepairLoopTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,folder,**options):
        store=configured_store(folder);settings=store.read()
        settings['roles']['planner']={'provider':'openai','model':'gpt-6.1-sol','vision':True,'reasoning_effort':'max'}
        settings['roles']['executor']={'provider':'openai','model':'gpt-6.1-terra','reasoning_effort':'max'};store.save(settings,{})
        job=Job('静态装配',Path(folder)/'jobs');job.output_dir.joinpath('old.png').write_bytes(PNG)
        job.output_dir.joinpath('model.SLDASM').write_bytes(b'immutable-fixture-native')
        job.output_dir.joinpath('design-acceptance.json').write_text(json.dumps({'verification':{'passed':True}}))
        api=RepairAPI(job,**{k:v for k,v in options.items() if k!='fail'})
        session=RepairSession(job,options.get('fail',False))
        if options.get('other_issue'):manifest(job.output_dir,0)
        def client(**kwargs):return AsyncOpenAI(**kwargs,http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api.handle)))
        plan=EngineeringPlan(summary='fixture',action='create',needs_clarification=False,supported=True,questions=[],steps=[],checks=[])
        with patch('workbench.engine.AsyncOpenAI',side_effect=client):
            error=None
            try:summary=await review_delivery(WorkbenchEngine(store),job,session,plan,store.role('planner'),store.role('executor'),'执行完成')
            except Exception as exc:error=exc;summary=''
        self.assertEqual((job.output_dir/'model.SLDASM').read_bytes(),b'immutable-fixture-native')
        return job,api,session,summary,error

    async def test_real_sdk_routes_sol_review_to_one_terra_repair_and_fresh_sol_review(self):
        with tempfile.TemporaryDirectory() as folder:
            job,api,session,summary,error=await self.exercise(folder)
            self.assertIsNone(error);self.assertEqual(len(session.calls),1);self.assertEqual(api.reviews,2)
            self.assertEqual(job.review_status['state'],'passed');self.assertIn('再次复核通过',summary)
            self.assertEqual([b['model'] for b in api.requests],['gpt-6.1-sol','gpt-6.1-terra','gpt-6.1-terra','gpt-6.1-sol'])
            self.assertTrue(all(b['reasoning']['effort']=='max' for b in api.requests));self.assertEqual([b['max_output_tokens'] for b in api.requests],[16384,128000,128000,16384])
            self.assertEqual(job.usage,{'input_tokens':80,'output_tokens':80})
            self.assertEqual(len(list((job.output_dir/'reviews').glob('round-*.json'))),2)
            self.assertTrue(all('round-1/' in a['name'] for a in job.artifacts if a['preview']))
            images=[i for m in api.requests[-1]['input'] if m.get('role')=='user' for i in m.get('content',[]) if i.get('type')=='input_image']
            self.assertEqual(len(images),4);self.assertTrue(all(i['detail']=='high' for i in images))
            self.assertFalse(job.review_reasons)

    async def test_second_rejection_is_retained_without_infinite_correction(self):
        with tempfile.TemporaryDirectory() as folder:
            job,api,session,summary,error=await self.exercise(folder,still_bad=True)
            self.assertIsNone(error);self.assertEqual(api.reviews,2);self.assertEqual(len(session.calls),1)
            self.assertEqual(job.review_status['state'],'unresolved');self.assertIn('视图标识错误',job.review_reasons)

    async def test_other_geometry_issue_does_not_trigger_view_repair(self):
        with tempfile.TemporaryDirectory() as folder:
            job,api,session,summary,error=await self.exercise(folder,other_issue=True)
            self.assertIsNone(error);self.assertEqual(api.reviews,1);self.assertFalse(session.calls)
            self.assertEqual(job.review_status['state'],'unresolved');self.assertIn('孔径错误',job.review_reasons)

    async def test_stop_after_review_prevents_repair_api_and_native_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            job,api,session,summary,error=await self.exercise(folder,cancel=True)
            self.assertIsInstance(error,JobStopped);self.assertEqual(api.reviews,1);self.assertEqual(len(api.requests),1);self.assertFalse(session.calls)

    async def test_native_repair_failure_is_not_replayed_or_sent_as_passed(self):
        with tempfile.TemporaryDirectory() as folder:
            job,api,session,summary,error=await self.exercise(folder,fail=True)
            self.assertIsNotNone(error);self.assertEqual(api.reviews,1);self.assertEqual(len(session.calls),1)
