import io,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
import httpx2
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from integrations.czuryk.reference_build import ReferenceGeometry
from integrations.czuryk.loft_spec import AircraftParameters,LoftComponent,resolved_components
from workbench.engine import ReferencePlan,WorkbenchEngine
from workbench.jobs import Job
from workbench.reference_inputs import ReferenceStore,pin_references
from workbench_support import configured_store,FakeMCP,ScriptedAPI


def component(name):
    return {'name':name,'axis':'X','color_rgb':[.9,.9,1.],
        'sections':[{'station_mm':s,'u_mm':30,'v_mm':20,'radius_u_mm':r,'radius_v_mm':r*.8}
                    for s,r in [(10,1),(20,8),(30,1)]]}


class LoftSpecTests(unittest.TestCase):
    def test_separate_jobs_never_share_a_native_document_title(self):
        with tempfile.TemporaryDirectory() as folder:
            jobs=[Job('新建飞机',Path(folder)/'jobs') for _ in range(2)]
            paths=[]
            for job in jobs:
                args={'params':{'path':str(job.output_dir/'model.SLDPRT')}}
                WorkbenchEngine.guard_arguments(job,SimpleNamespace(action='create'),'solidworks_save_document',args)
                paths.append(Path(args['params']['path']))
                self.assertTrue(paths[-1].stem.endswith('_'+job.id))
            self.assertNotEqual(paths[0].name,paths[1].name)

    def test_aircraft_generates_mirrored_editable_component_plan(self):
        spec=ReferenceGeometry(family='cartoon_aircraft',depth_mm=1,aircraft=AircraftParameters())
        parts=resolved_components(spec);names={p.name for p in parts}
        self.assertTrue({'Fuselage','BlueBelly','WingLeft','WingRight','TailFin','CockpitLeft','CockpitRight'}<=names)
        self.assertEqual(len(parts),17)
        self.assertEqual(len([p for p in parts if p.name.startswith('Window')]),8)
        self.assertLessEqual(sum(len(p.sections) for p in parts),100)
        self.assertIsNone(spec.expected_volume())
        body=next(p for p in parts if p.name=='Fuselage')
        belly=next(p for p in parts if p.name=='BlueBelly')
        for b,c in zip(body.sections,belly.sections):
            # Colored belly follows the local fuselage rather than a detached flat plank.
            self.assertLess(abs(b.v_mm-c.v_mm), b.radius_v_mm*.1)
            self.assertGreater(c.radius_v_mm,b.radius_v_mm*.90)
        with self.assertRaises(ValueError):spec.program()

    def test_invalid_loft_data_rejected_before_com(self):
        for data in [dict(component('Same'),sections=component('Same')['sections'][::-1]),
                     dict(component('Same'),color_rgb=[1,1,float('nan')]),
                     dict(component('bad/name'))]:
            with self.assertRaises(ValueError):LoftComponent(**data)
        with self.assertRaises(ValueError):
            ReferenceGeometry(family='loft_scene',depth_mm=1,components=[component('Same'),component('Same')])
        with self.assertRaises(ValueError):
            ReferenceGeometry(family='cartoon_aircraft',depth_mm=1)
        with self.assertRaises(ValueError):AircraftParameters(wingspan_mm=80,fuselage_width_mm=80)

    def test_profile_budget_is_bounded(self):
        parts=[]
        for i in range(24):
            p=component('Part'+str(i));p['sections']=[dict(p['sections'][1],station_mm=s) for s in range(10)]
            parts.append(p)
        with self.assertRaises(ValueError):ReferenceGeometry(family='loft_scene',depth_mm=1,components=parts)


class LoftRelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_weak_model_call_drives_bounded_native_batches_without_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);settings=configured_store(root);job=Job('按比例估建卡通形体',root/'jobs',reference_mode='approximate')
            store=ReferenceStore(root/'uploads');buf=io.BytesIO();Image.new('RGB',(50,40),'white').save(buf,'PNG')
            pin_references(job,store.resolve([store.add(buf.getvalue(),'reference.png')['id']]))
            geometry=ReferenceGeometry(family='loft_scene',depth_mm=1,components=[component('Part'+str(i)) for i in range(4)])
            plan=ReferencePlan(summary='四个圆润部件',action='create',needs_clarification=False,supported=True,
                questions=[],steps=['原生放样'],checks=['实体数和截面'],geometry=geometry,observations=[],assumptions=[])
            class MCP(FakeMCP):
                async def list_tools(self):
                    result=await super().list_tools()
                    result.tools.append(SimpleNamespace(name='solidworks_build_reference',description='bounded native loft',
                        inputSchema={'type':'object','properties':{'params':{'type':'object'}},'required':['params']}))
                    return result
                async def call_tool(self,name,args):
                    if name!='solidworks_build_reference':return await super().call_tool(name,args)
                    self.calls.append((name,args));start=args['params']['component_start']
                    self.active={'title':'model_'+job.id+'.SLDPRT','path':str(job.output_dir/('model_'+job.id+'.SLDPRT')),'type':1}
                    data={'status':'ok' if start==2 else 'in_progress','success':True,'complete':start==2,
                        'completed_components':start+2,'component_count':4,'document':self.active}
                    return SimpleNamespace(isError=False,structuredContent=data,content=[])
            class API(ScriptedAPI):
                def handle(self,request):
                    body=json.loads(request.content)
                    props=body.get('text',{}).get('format',{}).get('schema',{}).get('properties',{})
                    if 'needs_clarification' in props:
                        self.requests.append(body);output=self.message(plan.model_dump_json())
                    elif body.get('tools') and not any(i.get('type')=='function_call_output' for i in body.get('input',[]) if isinstance(i,dict)):
                        self.requests.append(body)
                        output=[{'id':'fc_scene','type':'function_call','call_id':'call_scene','name':'solidworks_build_reference',
                            'arguments':json.dumps({'params':{'spec_path':str(job.output_dir/'reference-spec.json'),'output_path':str(job.output_dir/('model_'+job.id+'.SLDPRT'))}}),'status':'completed'}]
                    else:return super().handle(request)
                    return httpx2.Response(200,json={'id':'resp_scene','object':'response','created_at':1700000000,'model':body['model'],
                        'status':'completed','output':output,'usage':{'input_tokens':20,'output_tokens':20,'total_tokens':40}})
            mcp=MCP();api=API()
            await WorkbenchEngine(settings,mcp.session,api.model).run(job)
            batches=[args['params']['component_start'] for name,args in mcp.calls if name=='solidworks_build_reference']
            self.assertEqual(batches,[0,2])
            weak=[r for r in api.requests if r.get('tools')]
            self.assertTrue(weak)
            self.assertNotIn('input_image',json.dumps(weak))
            self.assertNotEqual(job.phase,'completed') # Missing real CAD files cannot pass acceptance.
