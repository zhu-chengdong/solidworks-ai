import unittest,math
from pydantic import ValidationError
from engineering.pockets import PlanarCut,expected_edges
class CutGeometry(unittest.TestCase):
    def test_slot_uses_overall_length_not_center_spacing(self):
        op=PlanarCut(kind='slot',z_mm=12,center_mm=[0,0],length_mm=30,width_mm=8,angle_deg=30)
        self.assertAlmostEqual(math.dist(*op.slot_centers()),22)
        self.assertAlmostEqual(op.area_mm2(),22*8+math.pi*16)
        edges=expected_edges(op,0);self.assertEqual(len(edges['lines']),4);self.assertEqual(len(edges['arcs']),4)
    def test_polygon_area_does_not_depend_on_winding(self):
        points=[[-20,-10],[15,-10],[15,5],[5,15],[-20,15]]
        for values in (points,list(reversed(points))):
            op=PlanarCut(kind='pocket',z_mm=20,depth_mm=5,points_mm=values);self.assertEqual(op.area_mm2(),825)
            self.assertEqual(len(expected_edges(op,15)['lines']),15)
    def test_bad_profiles_and_nonfinite_input_are_rejected(self):
        for values in [dict(kind='slot',center_mm=[0,0],length_mm=8,width_mm=8),dict(kind='slot',center_mm=[float('inf'),0],length_mm=10,width_mm=8),
          dict(kind='pocket',points_mm=[[0,0],[10,10],[0,10],[10,0]])]:
            with self.assertRaises(ValidationError):PlanarCut(z_mm=12,**values)
    def test_plan_output_uses_supported_array_items_with_exact_xy_pairs(self):
        import json
        from agents import AgentOutputSchema
        from workbench.engine import EngineeringPlan
        schema=AgentOutputSchema(EngineeringPlan).json_schema()
        self.assertNotIn('prefixItems',json.dumps(schema))
        for point in ([0],[0,1,2]):
            with self.assertRaises(ValidationError):PlanarCut(kind='pocket',z_mm=10,points_mm=[point,[10,0],[0,10]])
if __name__=='__main__':unittest.main(verbosity=2)
