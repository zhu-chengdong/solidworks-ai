import json,tempfile,unittest
from pathlib import Path
from agents.exceptions import ModelBehaviorError
from workbench.engine import WorkbenchEngine,EngineeringPlan
from workbench.jobs import Job
from workbench_support import configured_store,FakeMCP
from pydantic import BaseModel,Field
from workbench.planning_repair import repair_context

MARKER='REJECTED_DRAFT_BODY_'*2000

class RepairEngine(WorkbenchEngine):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.prompts=[]
    async def structured(self,profile,prompt,output_type,job=None):
        self.prompts.append(prompt)
        if len(self.prompts)==1:
            exc=ModelBehaviorError('Invalid draft')
            exc.validation_feedback='A required design field is missing'
            exc.invalid_output=json.dumps({'large_invalid_field':MARKER})
            raise exc
        return EngineeringPlan(summary='Test stops before CAD',action='create',supported=False,needs_clarification=False,questions=[],steps=[],checks=[])

class PlanningRepairFlow(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_repair_preserves_request_and_logs_field_errors_without_rejected_body(self):
        with tempfile.TemporaryDirectory() as folder:
            mcp=FakeMCP();engine=RepairEngine(configured_store(folder),mcp.session)
            job=Job('新建一块30毫米安装板',Path(folder)/'jobs')
            await engine.run(job)
            self.assertEqual(len(engine.prompts),2)
            self.assertIn(job.requests[0],engine.prompts[1])
            self.assertNotIn(MARKER,engine.prompts[1])
            self.assertLess(len(engine.prompts[1])-len(engine.prompts[0]),6500)
            repair=next(e for e in job.events if e['kind']=='planning_repair')
            self.assertTrue(repair['validation_feedback']);self.assertTrue(repair['previous_json_omitted'])
            self.assertFalse(any(name.startswith('solidworks_create') for name,_ in mcp.calls))

    async def test_revision_repair_preserves_its_previous_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            mcp=FakeMCP();engine=RepairEngine(configured_store(folder),mcp.session)
            job=Job('修改前一方案',Path(folder)/'jobs');job.previous_context={'summary':'prior design'}
            await engine.run(job)
            self.assertIn(MARKER,engine.prompts[1])

    async def test_two_rejections_record_the_failure_and_stop_before_CAD(self):
        class RejectedEngine(RepairEngine):
            async def structured(self,profile,prompt,output_type,job=None):
                self.prompts.append(prompt)
                exc=ModelBehaviorError('Schema error');exc.invalid_output='{}';exc.validation_feedback='missing design'
                raise exc
        with tempfile.TemporaryDirectory() as folder:
            mcp=FakeMCP();engine=RejectedEngine(configured_store(folder),mcp.session)
            job=Job('新建明确的零件',Path(folder)/'jobs')
            with self.assertRaises(ModelBehaviorError):await engine.run(job)
            self.assertEqual(len(engine.prompts),2)
            self.assertTrue(any(e['kind']=='planning_rejected' and e['validation_feedback'] for e in job.events))
            self.assertFalse(any(name.startswith('solidworks_create') for name,_ in mcp.calls))

class PositivePlan(BaseModel):
    value:float=Field(gt=0)
    body:str=''

class RepairFeedback(unittest.TestCase):
    def error(self,previous,feedback='Specific SDK failure'):
        exc=ModelBehaviorError('Schema error');exc.invalid_output=previous;exc.validation_feedback=feedback
        return exc
    def test_numeric_field_error_excludes_the_large_input(self):
        feedback,previous=repair_context(self.error(json.dumps({'value':0,'body':MARKER})),PositivePlan,False)
        self.assertIn('value',feedback);self.assertIn('greater_than',feedback)
        self.assertNotIn(MARKER,feedback);self.assertIsNone(previous)
    def test_dictionary_drafts_produce_actionable_paths(self):
        feedback,_=repair_context(self.error({'body':MARKER}),PositivePlan,False)
        self.assertIn('value [missing]',feedback)
    def test_valid_draft_with_sdk_error_keeps_specific_fallback(self):
        feedback,previous=repair_context(self.error('{"value":1}','Tool output type mismatch'),PositivePlan,True)
        self.assertEqual(feedback,'Tool output type mismatch');self.assertEqual(previous,'{"value":1}')
    def test_fallback_and_revision_draft_are_redacted_and_feedback_bounded(self):
        secret='sk-placeholder-private-key'
        feedback,previous=repair_context(self.error('{"value":1,"body":"'+secret+'"}',secret+'x'*9000),PositivePlan,True)
        self.assertNotIn(secret,feedback);self.assertNotIn(secret,previous);self.assertLessEqual(len(feedback),6000)

if __name__=='__main__':unittest.main()
