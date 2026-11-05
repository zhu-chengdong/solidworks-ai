import math,tempfile,unittest,json
from pathlib import Path
from drawing2cad.parser import inspect_dxf,options,select_spec,DrawingError
from orthographic_fixtures import stepped_block,blind_plate


class OrthographicTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def drawing(self,**kw):
        path=self.root/'three-views.dxf';stepped_block(path,**kw);return path
    def test_three_views_determine_steps_and_local_hole_depths(self):
        data=inspect_dxf(self.drawing());spec,q=select_spec(data,options('按三视图和孔标注重建'))
        self.assertIsNone(q,q);self.assertEqual(spec['kind'],'orthographic');self.assertEqual(spec['size_mm'],[120,80,36])
        self.assertEqual(len(spec['layers']),2);self.assertAlmostEqual(spec['base_volume_mm3'],176640)
        self.assertEqual(len(spec['holes']),5)
        h={h['id']:h for h in spec['holes']}
        self.assertEqual(h['H1']['entry_z_mm'],36);self.assertEqual(h['H1']['bottom_z_mm'],24)
        self.assertEqual(h['H4']['entry_z_mm'],12);self.assertEqual(h['H4']['bottom_z_mm'],5)
        self.assertTrue(h['H2']['through']);self.assertFalse(h['H3']['through']);self.assertEqual(h['H3']['counterbore_depth_mm'],6)
        expected=176640-math.pi*(16*12+3.3**2*36+(6.5**2-3.3**2)*5+16*20+(49-16)*6+9*7+3.3**2*12)
        self.assertAlmostEqual(spec['expected_volume_mm3'],expected,places=6)
        json.dumps(spec)
    def test_missing_depth_clarifies_without_assuming_through(self):
        data=inspect_dxf(self.drawing(missing_depth=True));spec,q=select_spec(data,options('按三视图重建'))
        self.assertIsNone(spec);self.assertIn('H1',q)
        spec,q=select_spec(data,options('按三视图重建；H1 BLIND DEPTH12'))
        self.assertIsNone(q,q);self.assertFalse(spec['holes'][0]['through'])
    def test_dimension_conflict_stops_before_native(self):
        spec,q=select_spec(inspect_dxf(self.drawing(conflict=True)),options('按三视图重建'))
        self.assertIsNone(spec);self.assertIn('冲突',q)
    def test_mismatched_right_view_rejected(self):
        path=self.drawing();import ezdxf
        d=ezdxf.readfile(path);entity=list(d.modelspace().query('LWPOLYLINE[layer=="OUTLINE"]'))[2];entity.scale(1.1,1,1);d.saveas(path)
        with self.assertRaisesRegex(DrawingError,'不一致'):select_spec(inspect_dxf(path),options('按三视图重建'))
    def test_blind_depth_must_leave_a_floor(self):
        data=inspect_dxf(self.drawing());
        for a in data['annotations']:
            if a['text'].startswith('H1 '):a['text']='H1 DIA8 BLIND DEPTH40'
        with self.assertRaisesRegex(DrawingError,'底壁'):select_spec(data,options('按三视图重建'))
    def test_flat_bottom_requires_evidence_or_consent(self):
        data=inspect_dxf(self.drawing())
        data['annotations']=[a for a in data['annotations'] if 'FLAT BOTTOM' not in a['text']]
        self.assertIn('平底',select_spec(data,options('按三视图重建'))[1])
        self.assertIsNone(select_spec(data,options('按三视图重建，盲孔均为平底'))[1])
    def test_concentric_circles_are_not_guessed_as_counterbore(self):
        data=inspect_dxf(self.drawing())
        for a in data['annotations']:
            if a['text'].startswith('H2 '):a['text']='H2 DIA6.6 THRU'
        spec,q=select_spec(data,options('按三视图重建'))
        self.assertIsNone(spec);self.assertIn('同心圆',q)
    def test_complete_callout_override_replaces_original_without_duplication(self):
        data=inspect_dxf(self.drawing());spec,q=select_spec(data,options('按三视图重建；H3 DIA8 BLIND DEPTH20 CBORE DIA14 DEPTH6'))
        self.assertIsNone(q,q);self.assertEqual(next(h for h in spec['holes'] if h['id']=='H3')['cut_depth_mm'],20)
    def test_single_view_curved_plate_with_blind_and_counterbore(self):
        path=self.root/'plate.dxf';blind_plate(path);spec,q=select_spec(inspect_dxf(path),options('厚度20毫米，按孔标注建模'))
        self.assertIsNone(q,q);self.assertEqual(spec['kind'],'profile_holes');self.assertEqual(len(spec['holes']),2)
        expected=(7000-(4-math.pi)*64)*20-math.pi*(25*8+3.3**2*20+(36-3.3**2)*4)
        self.assertAlmostEqual(spec['expected_volume_mm3'],expected,places=6)
    def test_unknown_blind_hole_without_callout_never_becomes_through(self):
        path=self.root/'plate.dxf';blind_plate(path);data=inspect_dxf(path);data['leaders']=[]
        spec,q=select_spec(data,options('厚度20毫米，盲孔'))
        self.assertIsNone(spec);self.assertIn('孔径',q)
    def test_exploded_native_export_leaders_are_associated(self):
        path=self.drawing();import ezdxf
        d=ezdxf.readfile(path);m=d.modelspace()
        for leader in list(m.query('LEADER')):
            tip,tail=list(leader.vertices);x,y=tip[:2]
            for a,b in [((x,y),(x-2,y+1)),((x-2,y+1),(x-2,y-1)),((x-2,y-1),(x,y)),((x-2,y),tuple(tail)[:2])]:m.add_line(a,b,dxfattribs={'layer':'LEADERS'})
            m.delete_entity(leader)
        d.saveas(path);data=inspect_dxf(path);spec,q=select_spec(data,options('按三视图重建'))
        self.assertIsNone(q,q);self.assertEqual(len(spec['holes']),5);self.assertTrue(all(l.get('reconstructed_from_exported_strokes') for l in data['leaders']))
    def test_countersink_callout_not_misread_as_blind(self):
        data=inspect_dxf(self.drawing())
        for a in data['annotations']:
            if a['text'].startswith('H1 '):a['text']='H1 CSK DIA8 DEPTH12'
        with self.assertRaisesRegex(DrawingError,'沉头'):select_spec(data,options('按三视图重建'))
    def test_chinese_diameter_and_depth_notation(self):
        data=inspect_dxf(self.drawing())
        for a in data['annotations']:
            if a['text'].startswith('H1 '):a['text']='H1 φ8 盲孔 深12'
        spec,q=select_spec(data,options('按三视图重建'))
        self.assertIsNone(q,q);self.assertEqual(spec['holes'][0]['cut_depth_mm'],12)
    def test_native_filenames_are_unique_across_task_directories(self):
        from drawing2cad.native import artifact_paths
        a,_=artifact_paths(self.root/'task-a');b,_=artifact_paths(self.root/'task-b')
        self.assertNotEqual(a.name,b.name);self.assertEqual(artifact_paths(self.root/'task-a')[0],a)
    def test_unexplained_hidden_cavity_is_not_silently_filled(self):
        path=self.drawing();import ezdxf
        d=ezdxf.readfile(path);d.modelspace().add_line((5,5),(15,5),dxfattribs={'layer':'HIDDEN'});d.saveas(path)
        with self.assertRaisesRegex(DrawingError,'隐藏线'):select_spec(inspect_dxf(path),options('按三视图重建'))
    def test_depth_override_conflicting_with_hidden_bottom_is_rejected(self):
        with self.assertRaisesRegex(DrawingError,'隐藏线'):select_spec(inspect_dxf(self.drawing()),options('按三视图重建；H3 DIA8 BLIND DEPTH22 CBORE DIA14 DEPTH6'))
    def test_standard_dimension_layer_leaders_are_not_discarded(self):
        path=self.drawing();import ezdxf
        d=ezdxf.readfile(path)
        for e in d.modelspace().query('LEADER'):e.dxf.layer='DIM'
        d.saveas(path);spec,q=select_spec(inspect_dxf(path),options('按三视图重建'))
        self.assertIsNone(q,q);self.assertEqual(len(spec['holes']),5)
    def test_negative_through_note_requires_depth(self):
        data=inspect_dxf(self.drawing())
        for a in data['annotations']:
            if a['text'].startswith('H1 '):a['text']='H1 DIA8 NOT THROUGH'
        spec,q=select_spec(data,options('按三视图重建'))
        self.assertIsNone(spec);self.assertIn('H1',q)


if __name__=='__main__':unittest.main()
