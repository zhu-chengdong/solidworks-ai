import unittest
from engineering.spec import skill_context
from engineering.previews import view_specs,IDENTITY

class PreviewCapabilityContract(unittest.TestCase):
    def test_planner_declares_every_native_delivered_view(self):
        declared=skill_context()['native_design_workflow'].get('preview_views',[])
        for rotation in (IDENTITY,[0.,1.,0.,-1.,0.,0.,0.,0.,1.]):
            self.assertEqual(set(declared),set(view_specs(rotation)))
        self.assertEqual(len(declared),4)
