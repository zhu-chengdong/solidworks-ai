import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import httpx2
from openai import AsyncOpenAI
from agents.exceptions import ModelBehaviorError
from workbench.engine import WorkbenchEngine,EngineeringPlan,Review,ModelOutputLimit
from workbench.jobs import Job
from workbench_support import ScriptedAPI,configured_store,FakeMCP

class TruncatedAPI(ScriptedAPI):
    def handle(self,request):
        response=super().handle(request);body=response.json()
        body.update(status='incomplete',incomplete_details={'reason':'max_output_tokens'})
        return httpx2.Response(200,json=body)

class DetailedAPI(ScriptedAPI):
    def handle(self,request):
        body=super().handle(request).json()
        body['usage'].update(input_tokens_details={'cached_tokens':7},output_tokens_details={'reasoning_tokens':9})
        body['service_tier']='default'
        return httpx2.Response(200,json=body)

def max_store(folder):
    store=configured_store(folder);settings=store.read()
    settings['roles']['planner']={'provider':'openai','model':'gpt-6-astra','vision':True,'reasoning_effort':'max'}
    settings['roles']['executor']={'provider':'openai','model':'gpt-6.1-terra','reasoning_effort':'max'}
    store.save(settings,{})
    return store

class ModelObservationTests(unittest.IsolatedAsyncioTestCase):
    async def run_planning(self,api,folder):
        store=configured_store(folder);job=Job('自然语言装配',Path(folder)/'jobs')
        profile=store.role('planner',store.read())
        def client(**kwargs):
            return AsyncOpenAI(**kwargs,http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api.handle)))
        with patch('workbench.engine.AsyncOpenAI',side_effect=client):
            try:await WorkbenchEngine(store).structured(profile,'检查方案',EngineeringPlan,job)
            except (ModelBehaviorError,ModelOutputLimit) as exc:return job,exc
        return job,None

    async def test_incomplete_provider_response_records_usage_before_sdk_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            job,error=await self.run_planning(TruncatedAPI(),folder)
            self.assertIsInstance(error,ModelOutputLimit)
            self.assertEqual(job.usage,{'input_tokens':20,'output_tokens':20})
            event=next(e for e in job.events if e['kind']=='model_response')
            self.assertEqual(event['incomplete_reason'],'max_output_tokens')
            self.assertEqual(event['response_id'],'resp_test_1')
            self.assertNotIn('sk-test-placeholder',json.dumps(job.public()))

    async def test_complete_plan_gets_structural_capacity_without_double_counting(self):
        with tempfile.TemporaryDirectory() as folder:
            api=ScriptedAPI();job,error=await self.run_planning(api,folder)
            self.assertIsNone(error)
            self.assertEqual(api.requests[0]['max_output_tokens'],16384)
            self.assertEqual(job.usage,{'input_tokens':20,'output_tokens':20})
            events=[e for e in job.events if e['kind']=='model_response']
            self.assertEqual(len(events),1)
            self.assertEqual(events[0]['status'],'completed')
            self.assertEqual(events[0]['role'],'planner')

    async def test_openai_max_real_sdk_planning_execution_and_review_preserve_capacity_and_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            api=DetailedAPI();store=max_store(folder);job=Job('只读版本',Path(folder)/'jobs');mcp=FakeMCP();timeouts=[]
            def client(**kwargs):
                timeouts.append(kwargs['timeout'])
                return AsyncOpenAI(**kwargs,http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api.handle)))
            with patch('workbench.engine.AsyncOpenAI',side_effect=client):
                engine=WorkbenchEngine(store,session_factory=mcp.session)
                await engine.run(job)
                review=await engine.structured(store.role('planner'),'复核实际结果',Review,job)
            self.assertEqual(job.phase,'completed');self.assertTrue(review.passed)
            self.assertEqual(len(api.requests),4);self.assertTrue(all(t==1800 for t in timeouts))
            self.assertEqual([body['model'] for body in api.requests],['gpt-6-astra','gpt-6.1-terra','gpt-6.1-terra','gpt-6-astra'])
            for body in api.requests:
                self.assertEqual(body['reasoning']['effort'],'max')
                self.assertEqual(body['max_output_tokens'],128000 if body.get('tools') else 16384)
                self.assertFalse(body['store'])
                if body.get('tools'):self.assertFalse(body['parallel_tool_calls'])
                else:self.assertNotEqual(body.get('parallel_tool_calls'),True)
            events=[e for e in job.events if e['kind']=='model_response']
            self.assertEqual(len(events),4);self.assertEqual(events[-1]['role'],'review')
            self.assertEqual(job.usage,{'input_tokens':80,'output_tokens':80})
            for event in events:
                self.assertEqual(event['reasoning_effort'],'max');self.assertEqual(event['max_output_tokens'],128000 if event['role']=='executor' else 16384)
                self.assertEqual(event['input_cached_tokens'],7);self.assertEqual(event['reasoning_tokens'],9)
                self.assertEqual(event['usage_details']['input_tokens_details']['cached_tokens'],7)
                self.assertGreaterEqual(event['api_elapsed_seconds'],0)
                self.assertEqual(event['model'],event['actual_model'])
            self.assertEqual(len([e for e in job.events if e['kind']=='model_request']),4)
            self.assertFalse(any(name.startswith('solidworks_create') for name,_ in mcp.calls))
            self.assertNotIn('sk-test-placeholder',json.dumps(job.public()))

    async def test_max_incomplete_keeps_usage_and_observes_requested_effort(self):
        with tempfile.TemporaryDirectory() as folder:
            store=max_store(folder);job=Job('复杂装配',Path(folder)/'jobs');api=TruncatedAPI()
            def client(**kwargs):return AsyncOpenAI(**kwargs,http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api.handle)))
            with patch('workbench.engine.AsyncOpenAI',side_effect=client):
                with self.assertRaises(ModelOutputLimit):
                    await WorkbenchEngine(store).structured(store.role('planner'),'规划',EngineeringPlan,job)
            self.assertEqual(job.usage,{'input_tokens':20,'output_tokens':20})
            event=next(e for e in job.events if e['kind']=='model_response')
            self.assertEqual(event['reasoning_effort'],'max');self.assertEqual(event['max_output_tokens'],16384)
            self.assertEqual(event['status'],'incomplete');self.assertEqual(len(api.requests),1)
