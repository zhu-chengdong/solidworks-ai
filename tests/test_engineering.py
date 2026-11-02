import asyncio,hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from engineering.spec import DesignSpec,PartSpec
from workbench.cad_inputs import CadStore,pin_cad_inputs
from workbench.engine import WorkbenchEngine,EngineeringPlan,JobStopped
from workbench.jobs import Job
from workbench.settings import UserFacingError
from engineering.package import build_delivery
import zipfile


def assembly():
    return DesignSpec.model_validate({'document':'assembly','parts':[{'id':'plate','shape':'plate','length_mm':80,'width_mm':60,'thickness_mm':8}],
        'instances':[{'id':'base','part_id':'plate','fixed':True},{'id':'top','part_id':'plate','position_mm':[0,0,18]}],
        'mates':[{'id':'x','kind':'coincident','a':'base','b':'top','plane_a':'YZ','plane_b':'YZ'},
                 {'id':'y','kind':'coincident','a':'base','b':'top','plane_a':'XZ','plane_b':'XZ'},
                 {'id':'z','kind':'distance','a':'base','b':'top','distance_mm':18}]})


class EngineeringSchemaTests(unittest.TestCase):
    def test_rgb_range_is_visible_in_the_model_schema_and_not_silently_rescaled(self):
        schema=PartSpec.model_json_schema()['properties']['color_rgb']
        self.assertEqual(schema['items']['minimum'],0)
        self.assertEqual(schema['items']['maximum'],1)
        with self.assertRaises(ValueError):PartSpec(id='p',shape='plate',length_mm=20,width_mm=20,thickness_mm=8,color_rgb=[180,180,180])
        self.assertEqual(PartSpec(id='p',shape='plate',length_mm=20,width_mm=20,thickness_mm=8,color_rgb=[.7,.5,1]).color_rgb,[.7,.5,1])

    def test_signed_plane_distance_is_checked_before_any_native_write(self):
        raw=assembly().model_dump();raw['instances'][1]['position_mm'][2]=-18
        with self.assertRaisesRegex(ValueError,'flip must be True'):DesignSpec.model_validate(raw)
        raw['mates'][-1]['flip']=True
        self.assertEqual(DesignSpec.model_validate(raw).instances[1].position_mm[2],-18)

    def test_rotated_native_fixture_satisfies_plane_sign_and_alignment_contract(self):
        path=Path(__file__).resolve().parents[1]/'engineering/examples/bracket_shaft_plate.json'
        spec=DesignSpec.model_validate_json(path.read_text(encoding='utf-8'))
        self.assertEqual(len(spec.instances),7)
        raw=spec.model_dump();raw['mates'][0]['flip']=False
        with self.assertRaisesRegex(ValueError,'flip must be True'):DesignSpec.model_validate(raw)

    def test_family_dimensions_cannot_default_to_an_unrelated_mount(self):
        for shape in ['plate','shaft','enclosure','l_bracket']:
            with self.assertRaises(ValueError):PartSpec(id='part',shape=shape)
        shaft=PartSpec(id='shaft',shape='shaft',length_mm=80,diameter_mm=20)
        self.assertEqual(shaft.shape,'shaft')
        self.assertAlmostEqual(shaft.expected_volume(),25132.741228718343)

    def test_bad_hole_wall_and_reference_graph_rejected_before_cad(self):
        with self.assertRaises(ValueError):PartSpec(id='p',shape='plate',length_mm=20,width_mm=20,thickness_mm=2,holes=[{'x_mm':9,'y_mm':0,'radius_mm':2}])
        with self.assertRaises(ValueError):PartSpec(id='p',shape='enclosure',length_mm=20,width_mm=20,height_mm=10,wall_mm=6)
        raw=assembly().model_dump();raw['instances'][1]['fixed']=True
        with self.assertRaises(ValueError):DesignSpec.model_validate(raw)
        raw=assembly().model_dump();raw['mates']=[]
        with self.assertRaises(ValueError):DesignSpec.model_validate(raw)
        raw=assembly().model_dump();raw['instances'][1]['part_id']='unknown'
        with self.assertRaises(ValueError):DesignSpec.model_validate(raw)

    def test_repeated_instances_do_not_duplicate_part_definitions(self):
        plan=assembly();self.assertEqual(len(plan.parts),1);self.assertEqual(len(plan.instances),2)
        self.assertEqual([s['kind'] for s in plan.stages()],['part','assembly','mate','mate','mate','check','delivery'])

    def test_explicit_enclosure_cavity_has_positive_expected_volume(self):
        part=PartSpec(id='box',shape='enclosure',length_mm=100,width_mm=70,height_mm=30,wall_mm=3)
        self.assertEqual(part.expected_volume(),47568)


class CadInputTests(unittest.TestCase):
    def test_pinned_inputs_keep_hashes_and_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=CadStore(root/'uploads');raw=bytes.fromhex('D0CF11E0A1B11AE1')+b'native-container-test-only'
            meta=store.add(raw,'../../motor.SLDPRT');self.assertEqual(meta['name'],'motor.SLDPRT')
            job=Job('组装已有零件',root/'jobs');pin_cad_inputs(job,store.resolve([meta['id']]))
            pinned=job.output_dir/job.cad_inputs[0]['file'];self.assertEqual(pinned.read_bytes(),raw)
            self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(),meta['sha256'])
            (store.root/(meta['id']+'.SLDPRT')).write_bytes(b'changed')
            with self.assertRaises(UserFacingError):store.resolve([meta['id']])

    def test_unsupported_or_disguised_inputs_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            store=CadStore(folder)
            for data,name in [(b'MZexe','motor.SLDPRT'),(b'anything','assembly.SLDASM')]:
                with self.assertRaises(UserFacingError):store.add(data,name)
            with self.assertRaises(UserFacingError):store.resolve(['../../file'])

    def test_modern_2024_container_is_not_mistaken_for_invalid_ole(self):
        with tempfile.TemporaryDirectory() as folder:
            store=CadStore(folder)
            raw=b'1234'+bytes.fromhex('00000004')+b'header'+bytes.fromhex('34F6E64756E64737F2')+b'container-only-test'
            metadata=store.add(raw,'part.SLDPRT')
            self.assertEqual(store.resolve([metadata['id']])[0][0].read_bytes(),raw)


class DeliveryPackageTests(unittest.TestCase):
    def test_archive_contains_evidence_and_each_manifest_hash_matches_actual_member(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);native=root/'part.SLDPRT';native.write_bytes(b'cad-fixture')
            result=build_delivery(root,root/'delivery.zip',[native],{'verification':{'passed':True}})
            self.assertTrue(result['package_verified'])
            self.assertEqual(hashlib.sha256((root/'delivery.zip').read_bytes()).hexdigest(),result['package_sha256'])
            with zipfile.ZipFile(root/'delivery.zip') as archive:
                for name,digest in result['package_hashes'].items():self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(),digest)
                lines=archive.read('SHA256SUMS.txt').decode().splitlines()
                for line in lines:
                    digest,name=line.split('  ',1);self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(),digest)
                self.assertTrue(json.loads(archive.read('geometry-verification.json'))['verification']['passed'])
            with self.assertRaises(ValueError):build_delivery(root,root/'delivery.zip',[native],{})


class EngineeringRelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_stage_mutation_cannot_skip_or_escape_agreed_design(self):
        with tempfile.TemporaryDirectory() as folder:
            job=Job('组装孔板',Path(folder)/'jobs');design=assembly()
            plan=EngineeringPlan(summary='装配',action='create',needs_clarification=False,supported=True,questions=[],steps=[],checks=[],design=design)
            path=job.output_dir/'design-spec.json';path.write_text(design.model_dump_json(),encoding='utf-8')
            args={'params':{'spec_path':str(path),'output_dir':str(job.output_dir),'stage':0}}
            WorkbenchEngine.guard_arguments(job,plan,'solidworks_execute_design',args)
            args['params']['stage']=2
            with self.assertRaises(UserFacingError):WorkbenchEngine.guard_arguments(job,plan,'solidworks_execute_design',args)
            args['params']['stage']=0;path.write_text('{}')
            with self.assertRaises(UserFacingError):WorkbenchEngine.guard_arguments(job,plan,'solidworks_execute_design',args)

    async def test_cancel_between_native_stages_prevents_next_write(self):
        with tempfile.TemporaryDirectory() as folder:
            job=Job('组装孔板',Path(folder)/'jobs');design=assembly();calls=[]
            plan=SimpleNamespace(design=design)
            class Session:
                async def call_tool(self,name,args):
                    i=args['params']['stage'];calls.append(i)
                    if i==1:job.cancel.set()
                    return SimpleNamespace(isError=False,structuredContent={'status':'ok','completed_stages':i+1},content=[])
            with self.assertRaises(JobStopped):await WorkbenchEngine.execute_design(None,job,Session(),plan,{'params':{}})
            self.assertEqual(calls,[0,1])

    async def test_native_stage_failure_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as folder:
            job=Job('组装孔板',Path(folder)/'jobs');calls=[]
            class Session:
                async def call_tool(self,name,args):
                    i=args['params']['stage'];calls.append(i)
                    return SimpleNamespace(isError=i==2,structuredContent={'status':'error' if i==2 else 'ok','completed_stages':i+1,'message':'native failure'},content=[])
            with self.assertRaises(UserFacingError):await WorkbenchEngine.execute_design(None,job,Session(),SimpleNamespace(design=assembly()),{'params':{}})
            self.assertEqual(calls,[0,1,2])
