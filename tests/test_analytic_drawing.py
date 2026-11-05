import math,tempfile,unittest
from pathlib import Path
from drawing2cad.examples import analytic_housing
from drawing2cad.parser import inspect_dxf,select_spec,options,DrawingError
from drawing2cad.analytic import intervals,integrate

class AnalyticDrawingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'housing.dxf'
    def plan(self,**kw):
        analytic_housing(self.path,**kw);return select_spec(inspect_dxf(self.path),options('按三视图和孔标注建模'))
    def test_sloped_three_views_side_axes_and_cones(self):
        s,q=self.plan();self.assertIsNone(q,q);self.assertEqual(s['kind'],'orthographic_analytic');self.assertEqual(s['size_mm'],[120,80,50]);self.assertEqual(s['base_volume_mm3'],432000)
        holes={h['id']:h for h in s['holes']};self.assertEqual(holes['H1']['axis'],'y');self.assertEqual(holes['H3']['axis'],'x');self.assertEqual(holes['H2']['axis'],'z');self.assertEqual(holes['H3']['countersink_angle_deg'],82)
        self.assertAlmostEqual(holes['H1']['drill_point_height_mm'],4/math.tan(math.radians(59)))
        self.assertEqual(s['hidden_lines_checked'],12)
    def test_curved_front_is_an_exact_arc_not_polygon(self):
        s,q=self.plan(curved=True);self.assertIsNone(q,q);self.assertTrue(any(p['kind']=='arc' for p in s['profiles']['front']));self.assertAlmostEqual(s['base_volume_mm3'],(1000+1250*math.pi)*60)
        self.assertEqual({h['axis'] for h in s['holes']},{'y'})
    def test_total_depth_differs_from_cylinder_depth(self):
        a,_=self.plan();b,q=self.plan(total_depth=True);self.assertIsNone(q,q);ha=next(h for h in a['holes'] if h['id']=='H1');hb=next(h for h in b['holes'] if h['id']=='H1')
        self.assertAlmostEqual(ha['cut_depth_mm']-hb['cut_depth_mm'],ha['drill_point_height_mm']);self.assertAlmostEqual(hb['cut_depth_mm']+hb['drill_point_height_mm'],18)
    def test_missing_countersink_angle_asks_before_build(self):
        s,q=self.plan(missing_angle=True);self.assertIsNone(s);self.assertIn('夹角',q)
    def test_ambiguous_drill_depth_is_not_guessed(self):
        analytic_housing(self.path);d=inspect_dxf(self.path)
        for a in d['annotations']:a['text']=a['text'].replace('CYL DEPTH18','DEPTH18')
        s,q=select_spec(d,options('三视图'));self.assertIsNone(s);self.assertIn('圆柱段',q)
    def test_point_cannot_break_through_bottom(self):
        analytic_housing(self.path);d=inspect_dxf(self.path)
        for a in d['annotations']:a['text']=a['text'].replace('CYL DEPTH18','CYL DEPTH79')
        with self.assertRaisesRegex(DrawingError,'底壁'):select_spec(d,options('三视图'))
    def test_invalid_countersink_angle_is_rejected(self):
        analytic_housing(self.path);d=inspect_dxf(self.path)
        for a in d['annotations']:a['text']=a['text'].replace('ANGLE90','ANGLE180')
        with self.assertRaisesRegex(DrawingError,'夹角'):select_spec(d,options('三视图'))
    def test_cross_axis_hole_overlap_rejected(self):
        analytic_housing(self.path);d=inspect_dxf(self.path)
        # Move right-axis hole into the top through-hole's Y envelope.
        right=next(v for v in d['views'] if v['bounds_mm'][0]>150)
        for loop in right['inner']:loop[0]['center'][0]-=28
        for leader in d['leaders']:
            if leader['points_mm'][0][0]>150:leader['points_mm'][0][0]-=28
        with self.assertRaisesRegex(DrawingError,'相交'):select_spec(d,options('三视图'))
    def test_unknown_hidden_structure_rejected(self):
        analytic_housing(self.path);d=inspect_dxf(self.path);d['hidden_segments']=[[[5,5],[10,5]]]
        with self.assertRaisesRegex(DrawingError,'隐藏线'):select_spec(d,options('三视图'))
    def test_numeric_integrator_checks_polynomial(self):self.assertAlmostEqual(integrate(lambda x:x*x,0,3),9)
    def test_two_sloped_silhouettes_have_independent_expected_volume(self):
        from drawing2cad.analytic import base_volume
        from drawing2cad.native_advanced import _segments
        profiles={'top':_segments([[0,0],[120,0],[120,80],[0,80]]),'front':_segments([[0,0],[120,0],[120,50],[60,50],[0,30]]),'right':_segments([[0,0],[80,0],[80,50],[40,50],[0,20]])}
        volume,method=base_volume(profiles,[120,80,50]);self.assertAlmostEqual(volume,1136000/3,places=3);self.assertIn('integration',method)
    def test_partial_cone_override_is_not_silently_ignored(self):
        analytic_housing(self.path)
        with self.assertRaisesRegex(DrawingError,'完整'):select_spec(inspect_dxf(self.path),options('三视图；H2 ANGLE82'))
    def test_chinese_roles_select_curved_route_without_magic_prompt(self):
        from drawing2cad.analytic import needs_analytic
        analytic_housing(self.path,curved=True);data=inspect_dxf(self.path)
        names={'TOP':'俯视图','FRONT':'主视图','RIGHT':'右视图'}
        data['annotations']=[{**a,'text':names[a['text']]} for a in data['annotations'] if a['text'] in names]
        self.assertTrue(needs_analytic(data,options('按图建模')))
    def test_another_holes_flat_bottom_does_not_define_this_hole(self):
        analytic_housing(self.path,curved=True);data=inspect_dxf(self.path)
        for a in data['annotations']:
            if a['text'].startswith('H1 '):a['text']='H1 DIA8 BLIND DEPTH20'
        spec,q=select_spec(data,options('三视图'));self.assertIsNone(spec);self.assertIn('H1',q);self.assertIn('平底',q)

if __name__=='__main__':unittest.main()
