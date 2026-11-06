import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import httpx2
from openai import AsyncOpenAI
from workbench.engine import WorkbenchEngine,ModelOutputLimit,model_settings
from workbench.jobs import Job
from workbench.settings import SettingsStore,UserFacingError
from workbench_support import configured_store,FakeMCP
from test_openai_chat_highest import HighestChatAPI

class BudgetSettings(unittest.TestCase):
    def test_budget_persists_separately_from_max_reasoning(self):
        with tempfile.TemporaryDirectory() as folder:
            store=configured_store(folder);settings=store.read()
            settings['roles']['planner']['reasoning_effort']='max';settings['planner_token_budget']=32768
            store.save(settings,{})
            profile=store.role('planner');self.assertEqual(profile['reasoning_effort'],'max');self.assertEqual(profile['token_budget'],32768)
            self.assertEqual(SettingsStore(store.root,store.vault).read()['planner_token_budget'],32768)
    def test_invalid_budgets_are_rejected(self):
        for value in (True,0,1023,128001,16384.5,'16384'):
            with self.subTest(value=value),self.assertRaises(UserFacingError):SettingsStore.validate({'planner_token_budget':value})
    def test_explicit_budget_preserves_highest_effort_and_executor_capacity(self):
        for provider,style,model,full,effort in [('openai','chat_completions','gpt-6.1-sol',128000,'xhigh'),('openai','responses','gpt-6.1-sol',128000,'max'),('deepseek','chat_completions','deepseek-flash',131072,'max')]:
            profile={'provider':provider,'api_style':style,'model':model,'reasoning_effort':'max'}
            explicit=model_settings(profile,'planner',16384);executor=model_settings(profile,'executor')
            self.assertEqual(explicit.reasoning.effort,effort)
            actual=explicit.extra_args['max_completion_tokens'] if provider=='openai' and style=='chat_completions' else explicit.extra_args['max_tokens'] if provider=='deepseek' else explicit.max_tokens
            original=executor.extra_args['max_completion_tokens'] if provider=='openai' and style=='chat_completions' else executor.extra_args['max_tokens'] if provider=='deepseek' else executor.max_tokens
            self.assertEqual(actual,16384);self.assertEqual(original,full)

class LengthAPI(HighestChatAPI):
    def __init__(self,budgets=(16384,32768),always=False):super().__init__(budgets);self.always=always
    def handle(self,request):
        body=json.loads(request.content)
        is_chat=request.url.path.endswith('/chat/completions')
        self.length=is_chat and (self.always or not self.requests)
        response=super().handle(request)
        if is_chat and self.length and response.status_code==200:
            data=response.json();budget=body['max_completion_tokens']
            data['usage'].update(completion_tokens=budget,total_tokens=20+budget,completion_tokens_details={'reasoning_tokens':budget})
            return httpx2.Response(200,json=data)
        return response

class BoundedPlanning(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,folder,api,budget=16384):
        store=configured_store(folder);settings=store.read();settings['providers']['openai']['api_style']='chat_completions'
        settings['planner_token_budget']=budget
        settings['roles']['planner']={'provider':'openai','model':'gpt-6.1-sol','vision':True,'reasoning_effort':'max'}
        settings['roles']['executor']={'provider':'openai','model':'gpt-6.1-terra','reasoning_effort':'max'};store.save(settings,{})
        job=Job('仅读取实际版本',Path(folder)/'jobs');mcp=FakeMCP()
        def client(**kwargs):return AsyncOpenAI(**kwargs,http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api.handle)))
        error=None
        with patch('workbench.engine.AsyncOpenAI',side_effect=client):
            try:await WorkbenchEngine(store,mcp.session).run(job)
            except ModelOutputLimit as exc:error=exc
        return job,mcp,error
    async def test_one_budget_retry_keeps_max_and_counts_both_responses(self):
        with tempfile.TemporaryDirectory() as folder:
            api=LengthAPI();job,mcp,error=await self.exercise(folder,api)
            self.assertIsNone(error);self.assertEqual(job.phase,'completed')
            self.assertEqual([e['max_output_tokens'] for e in job.events if e['kind']=='model_request'],[16384,32768,128000,128000])
            self.assertEqual([e['reasoning_effort'] for e in job.events if e['kind']=='model_request'],['xhigh','xhigh','max','max'])
            self.assertEqual(job.usage,{'input_tokens':80,'output_tokens':16454})
            self.assertEqual(sum(e['kind']=='planning_budget_retry' for e in job.events),1)
            self.assertFalse(any(name.startswith('solidworks_create') for name,_ in mcp.calls))
    async def test_second_truncation_stops_before_CAD(self):
        with tempfile.TemporaryDirectory() as folder:
            api=LengthAPI(always=True);job,mcp,error=await self.exercise(folder,api)
            self.assertIsInstance(error,ModelOutputLimit);self.assertEqual(len(api.requests),2)
            self.assertEqual(job.usage,{'input_tokens':40,'output_tokens':49152})
            self.assertFalse(any(name.startswith('solidworks_create') for name,_ in mcp.calls))
    async def test_explicit_maximum_budget_is_respected_without_unbounded_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            api=LengthAPI((128000,),always=True);job,mcp,error=await self.exercise(folder,api,128000)
            self.assertIsInstance(error,ModelOutputLimit);self.assertEqual(len(api.requests),1)
            self.assertEqual(job.usage['output_tokens'],128000)
    async def test_free_pool_budget_is_not_changed_or_retried(self):
        class TruncatedEngine(WorkbenchEngine):
            count=0
            async def structured(self,*args,**kwargs):
                self.count+=1;raise ModelOutputLimit('free pool output limit')
        with tempfile.TemporaryDirectory() as folder:
            store=configured_store(folder);planner={**store.role('planner'),'transport':'magpie','output_limit':32768}
            mcp=FakeMCP();engine=TruncatedEngine(store,mcp.session);job=Job('新建零件',Path(folder)/'jobs')
            with patch('workbench.magpie.route_profiles',return_value=(planner,store.role('executor'))),self.assertRaises(ModelOutputLimit):await engine.run(job)
            self.assertEqual(engine.count,1);self.assertFalse(any(e['kind']=='planning_budget_retry' for e in job.events))

if __name__=='__main__':unittest.main()
