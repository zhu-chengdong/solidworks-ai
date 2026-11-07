import copy,hashlib,io,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace as Obj
from pydantic import ValidationError
from engineering.assembly_drawing_spec import AssemblyDrawingRequest,validate_bom,validate_balloons
from workbench.assembly_inputs import inspect_archive,pin_archive
from workbench.cad_inputs import CadStore,pin_cad_inputs
from workbench.settings import UserFacingError
from engineering.resource_budget import require_headroom
from engineering.assembly_drawing_layout import arrange,crossing_count,project_component,select_tip
from engineering.assembly_drawing import check_balloon_evidence

NATIVE=bytes.fromhex('D0CF11E0A1B11AE1')+b'fixture-container-not-native-geometry'
def zipped(entries):
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in entries:archive.writestr(name,data)
    return raw.getvalue()

class AssemblyInputTests(unittest.TestCase):
    def test_only_native_dependencies_are_pinned_and_hashes_are_preserved(self):
        raw=zipped([('assembly.SLDASM',NATIVE),('parts/p.SLDPRT',NATIVE),('preview.png',b'not-cad')])
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);store=CadStore(root/'upload');meta=store.add(raw,'assembly.zip')
            job=Obj(output_dir=root/'job',cad_inputs=[],save=lambda:None)
            pin_cad_inputs(job,store.resolve([meta['id']]))
            item=job.cad_inputs[0];self.assertEqual(len(item['documents']),2)
            self.assertFalse(list((root/'job').rglob('preview.png')))
            self.assertTrue((root/'job'/item['assembly_file']).is_file())
            for d in item['documents']:self.assertEqual(hashlib.sha256((root/'job'/d['file']).read_bytes()).hexdigest(),d['sha256'])

    def test_unsafe_paths_ambiguous_parts_nested_assemblies_and_disguised_cad_are_rejected(self):
        common=[('a.SLDASM',NATIVE),('p.SLDPRT',NATIVE)]
        cases=[common+[('../escape.txt',b'x')],common+[('p.sldprt',NATIVE)],common+[('another/a.SLDASM',NATIVE)],
               [('a.SLDASM',b'MZfake'),('p.SLDPRT',NATIVE)],common+[('parts/P.SLDPRT',NATIVE)],common+[('C:/unsafe.txt',b'x')]]
        for entries in cases:
            with self.subTest(entries=[e[0] for e in entries]),self.assertRaises(UserFacingError):inspect_archive(zipped(entries))

    def test_archive_tampering_after_upload_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            store=CadStore(temporary);meta=store.add(zipped([('a.SLDASM',NATIVE),('p.SLDPRT',NATIVE)]),'a.zip')
            (Path(temporary)/(meta['id']+'.zip')).write_bytes(b'changed')
            with self.assertRaises(UserFacingError):store.resolve([meta['id']])

class AssemblyAssociations(unittest.TestCase):
    def setUp(self):
        self.components=[{'name':'base-1','path':'base.SLDPRT'},{'name':'bracket-1','path':'bracket.SLDPRT'},{'name':'bracket-2','path':'bracket.SLDPRT'}]
        self.rows=[{'item':'1','quantity':1,'components':['base-1']},{'item':'2','quantity':2,'components':['bracket-1','bracket-2']}]
        self.balloons=[{'component':c['name'],'item':'1' if i==0 else '2','is_bom_balloon':True,'upper_text_content':1,'text_style':2,'attached_count':1} for i,c in enumerate(self.components)]
    def test_repeated_instances_share_one_native_bom_row_and_keep_separate_balloons(self):
        validate_bom(self.rows,self.components);validate_balloons(self.balloons,self.rows,self.components)
    def test_wrong_quantity_duplicate_row_and_missing_component_are_rejected(self):
        for change in ('quantity','duplicate','missing'):
            rows=copy.deepcopy(self.rows)
            if change=='quantity':rows[1]['quantity']=1
            elif change=='duplicate':rows[1]['item']='1'
            else:rows.pop()
            with self.subTest(change=change),self.assertRaises(ValueError):validate_bom(rows,self.components)
    def test_custom_text_detached_reference_and_wrong_item_cannot_pass_as_bom_balloons(self):
        for field,value in [('upper_text_content',0),('is_bom_balloon',False),('attached_count',0),('item','9')]:
            balloons=copy.deepcopy(self.balloons);balloons[1][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_balloons(balloons,self.rows,self.components)
        with self.assertRaises(ValueError):validate_balloons(self.balloons[:-1],self.rows,self.components)
    def test_unsupported_drawing_fields_and_nonfinite_scale_are_rejected(self):
        for fields in ({'scale':float('nan')},{'bom':False},{'exploded':True}):
            with self.subTest(fields=fields),self.assertRaises(ValidationError):AssemblyDrawingRequest(**fields)

class ResourceAndLeaderTests(unittest.TestCase):
    def test_reopen_preserves_attachment_tip_and_identity_but_allows_circle_start_regeneration(self):
        before=[{'component':'guide-1','item':'5','position_m':[.04,.18,0.],'leader_points_m':[.043,.18,0.,.11,.16,0.]}]
        after=copy.deepcopy(before);after[0]['leader_points_m'][0]+=.0002
        check_balloon_evidence(after,before)
        after[0]['leader_points_m'][3]+=.001
        with self.assertRaises(RuntimeError):check_balloon_evidence(after,before)
        after=copy.deepcopy(before);after[0]['component']='shaft-1'
        with self.assertRaises(RuntimeError):check_balloon_evidence(after,before)

    def test_attachment_uses_instance_pose_and_avoids_coincident_foreign_outlines(self):
        identity=[1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.]
        moved=list(identity);moved[9:12]=[.04,.08,0.]
        view=list(identity);view[12]=.5;view[9:12]=[.1,.2,0.]
        for actual,expected in zip(project_component([.02,0.,0.],moved,view),[.13,.24,0.]):self.assertAlmostEqual(actual,expected)
        edges=[[[0.,0.,0.],[.02,0.,0.]],[[0.,.01,0.],[.02,.01,0.]]]
        index,tip,clearance=select_tip(edges,[[[0.,0.,0.],[.02,0.,0.]]])
        self.assertEqual(index,1);self.assertEqual(tip,[.01,.01,0.]);self.assertGreater(clearance,.009)

    def test_free_ram_does_not_bypass_exhausted_commit(self):
        with self.assertRaises(ValueError):require_headroom({'available_physical':10*1024**3,'available_commit':2*1024**3},opening=True)
        require_headroom({'available_physical':10*1024**3,'available_commit':6*1024**3},opening=True)

    def test_actual_tip_assignment_removes_crossings_without_changing_identity(self):
        tips={'a':[.15,.15],'b':[.10,.22],'c':[.14,.20],'d':[.095,.18],'e':[.125,.23],'f':[.17,.14],'g':[.13,.17]}
        layout=arrange(tips)
        self.assertEqual(set(layout),set(tips));self.assertEqual(len({tuple(p) for p in layout.values()}),7)
        self.assertEqual(crossing_count([(layout[n],tips[n]) for n in tips]),0)

    def test_assignment_cost_matches_exhaustive_small_case(self):
        import itertools,math
        tips={'a':[.15,.15],'b':[.10,.22],'c':[.14,.20],'d':[.095,.18]}
        chosen=arrange(tips);names=sorted(tips);anchors=list(chosen.values())
        best=min(sum(math.dist(tips[n],a) for n,a in zip(names,perm)) for perm in itertools.permutations(anchors))
        self.assertAlmostEqual(sum(math.dist(tips[n],chosen[n]) for n in names),best,places=12)
