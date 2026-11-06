import json,unittest
from engineering.spec import PartSpec
from engineering.previews import view_specs,IDENTITY
from workbench.planning_contract import new_task_prompt
class PlanningContract(unittest.TestCase):
    def test_new_task_contract_tracks_actual_schema_and_preview_delivery(self):
        prompt=new_task_prompt(['新建零件'],{'status':'ok'})
        data=json.loads(prompt.split('\n',1)[1]);contract=data['原生参数契约']
        self.assertEqual(contract['part_fields'],list(PartSpec.model_fields))
        self.assertEqual(contract['preview_views'],list(view_specs(IDENTITY)))
        self.assertEqual(len(contract['preview_views']),4)
        self.assertEqual('materials' in contract,'material' in PartSpec.model_fields)
        for text in ('不得猜造','不能覆盖','Schema无法完整表达','零Fix'):
            self.assertIn(text,prompt)
if __name__=='__main__':unittest.main()
