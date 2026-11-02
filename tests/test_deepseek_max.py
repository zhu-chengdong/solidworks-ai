import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import httpx2
from openai import AsyncOpenAI
from agents.exceptions import ModelBehaviorError
from workbench.engine import WorkbenchEngine,EngineeringPlan,safe_error
from workbench.jobs import Job
from workbench.settings import SettingsStore,UserFacingError
from workbench_support import configured_store,FakeMCP

class MaxChatAPI:
    def __init__(self,invalid_first=False,length=False,plan=None,blank_first=False):self.requests=[];self.invalid_first=invalid_first;self.length=length;self.plan=plan;self.blank_first=blank_first
    def handle(self,request):
        body=json.loads(request.content);self.requests.append(body)
        private='mock-private-reasoning'
        if self.length:
            message={'role':'assistant','content':None,'reasoning_content':private};finish='length'
        elif not body.get('tools'):
            text='invalid JSON' if self.invalid_first and len(self.requests)==1 else json.dumps(self.plan or {'summary':'读取实际版本','action':'inspect','needs_clarification':False,'supported':True,'questions':[],'steps':['读取连接'],'checks':['版本'],'design':None,'assumptions':[]})
            if self.blank_first and len(self.requests)==1:text='   '
            message={'role':'assistant','content':text,'reasoning_content':private};finish='stop'
        elif not any(m.get('role')=='tool' for m in body['messages']):
            message={'role':'assistant','content':None,'reasoning_content':private,'tool_calls':[{'id':'max_call','type':'function','function':{'name':'solidworks_connect','arguments':'{"params":{}}'}}]};finish='tool_calls'
        else:
            message={'role':'assistant','content':'已读取原生连接。','reasoning_content':private};finish='stop'
        return httpx2.Response(200,json={'id':'ds-response-'+str(len(self.requests)),'object':'chat.completion','created':1700000000,'model':'deepseek-flash','choices':[{'index':0,'message':message,'finish_reason':finish}],
            'usage':{'prompt_tokens':20,'completion_tokens':30,'total_tokens':50,'completion_tokens_details':{'reasoning_tokens':10}}})

def max_store(folder):
    store=configured_store(folder);settings=store.read()
    settings['roles']['planner']={'provider':'deepseek','model':'deepseek-flash','vision':True,'reasoning_effort':'max'}
    settings['roles']['executor']={'provider':'deepseek','model':'deepseek-flash','reasoning_effort':'max'}
    store.save(settings,{'deepseek':'sk-deepseek-test-not-real'})
    return store

class DeepSeekMaxTests(unittest.IsolatedAsyncioTestCase):
    async def run_engine(self,folder,api):
        store=max_store(folder);job=Job('只读实际版本',Path(folder)/'jobs');mcp=FakeMCP()
        def client(**kwargs):return AsyncOpenAI(**kwargs,http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api.handle)))
        with patch('workbench.engine.AsyncOpenAI',side_effect=client):await WorkbenchEngine(store,session_factory=mcp.session).run(job)
        return store,job,mcp

    async def test_max_persists_and_reasoning_is_replayed_through_real_sdk_tool_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            api=MaxChatAPI();store,job,mcp=await self.run_engine(folder,api)
            reloaded=SettingsStore(store.root,store.vault).read()
            self.assertTrue(all(r['reasoning_effort']=='max' for r in reloaded['roles'].values()))
            self.assertEqual(job.phase,'completed');self.assertEqual(len(api.requests),3)
            for body in api.requests:
                self.assertEqual(body['reasoning_effort'],'max');self.assertEqual(body['thinking'],{'type':'enabled'})
                self.assertEqual(body['max_tokens'],131072)
                self.assertEqual(body.get('response_format'),None if body.get('tools') else {'type':'json_object'})
            replay=next(m for m in api.requests[-1]['messages'] if m.get('role')=='assistant' and m.get('tool_calls'))
            self.assertEqual(replay['reasoning_content'],'mock-private-reasoning')
            events=[e for e in job.events if e['kind']=='model_response']
            self.assertEqual(len(events),3);self.assertTrue(all(e['reasoning_effort']=='max' and e['max_output_tokens']==131072 for e in events))
            self.assertEqual(job.usage,{'input_tokens':60,'output_tokens':90})
            self.assertNotIn('mock-private-reasoning',json.dumps(job.public()))
            self.assertNotIn('sk-deepseek-test',json.dumps(job.public()))

    async def test_invalid_json_replans_once_before_any_native_write(self):
        with tempfile.TemporaryDirectory() as folder:
            api=MaxChatAPI(invalid_first=True);store,job,mcp=await self.run_engine(folder,api)
            self.assertEqual(job.phase,'completed')
            self.assertEqual(sum(e['kind']=='planning_repair' for e in job.events),1)
            self.assertFalse(any(name.startswith('solidworks_create') for name,_ in mcp.calls))
            self.assertEqual(job.usage,{'input_tokens':80,'output_tokens':120})
            repaired=json.dumps(api.requests[1]['messages'],ensure_ascii=False)
            self.assertIn('json_invalid',repaired)
            self.assertIn('invalid JSON',repaired)
            diagnostics=list((job.output_dir/'validation').glob('*-invalid-*.json'))
            self.assertEqual(len(diagnostics),1)
            self.assertNotIn('mock-private-reasoning',diagnostics[0].read_text())

    async def test_truncated_chat_response_keeps_usage_and_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            store=max_store(folder);job=Job('完整方案',Path(folder)/'jobs');api=MaxChatAPI(length=True)
            def client(**kwargs):return AsyncOpenAI(**kwargs,http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api.handle)))
            with patch('workbench.engine.AsyncOpenAI',side_effect=client):
                try:await WorkbenchEngine(store).structured(store.role('planner'),'返回方案',EngineeringPlan,job)
                except Exception as exc:self.assertIn('输出上限',safe_error(exc))
                else:self.fail('Truncated output must not be accepted')
            self.assertEqual(job.usage,{'input_tokens':20,'output_tokens':30})
            self.assertEqual(job.events[-1]['status'],'incomplete')
            self.assertEqual(len(api.requests),1)

    async def test_json_mode_blank_output_repairs_once_without_any_native_write(self):
        with tempfile.TemporaryDirectory() as folder:
            api=MaxChatAPI(blank_first=True);store,job,mcp=await self.run_engine(folder,api)
            self.assertEqual(job.phase,'completed')
            self.assertEqual(sum(e['kind']=='planning_repair' for e in job.events),1)
            self.assertTrue(all(body['response_format']=={'type':'json_object'} for body in api.requests if not body.get('tools')))
            self.assertFalse(any(name.startswith('solidworks_create') for name,_ in mcp.calls))
            diagnostic=json.loads(next((job.output_dir/'validation').glob('*-invalid-*.json')).read_text())
            self.assertEqual(diagnostic['final_output'],'')
            self.assertEqual(job.usage,{'input_tokens':80,'output_tokens':120})

    async def test_geometry_error_keeps_precise_feedback_without_relaxing_mate_rules(self):
        from test_engineering import assembly
        design=assembly().model_dump();design['instances'][1]['position_mm'][2]=-18
        plan={'summary':'装配','action':'create','needs_clarification':False,'supported':True,'questions':[],'steps':[],'checks':[],'design':design,'assumptions':[]}
        with tempfile.TemporaryDirectory() as folder:
            store=max_store(folder);job=Job('装配',Path(folder)/'jobs');api=MaxChatAPI(plan=plan)
            def client(**kwargs):return AsyncOpenAI(**kwargs,http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api.handle)))
            with patch('workbench.engine.AsyncOpenAI',side_effect=client):
                with self.assertRaises(ModelBehaviorError) as caught:
                    await WorkbenchEngine(store).structured(store.role('planner'),'返回方案',EngineeringPlan,job)
            self.assertIn('flip must be True',caught.exception.validation_feedback)
            diagnostic=json.loads(next((job.output_dir/'validation').glob('*-invalid-*.json')).read_text())
            self.assertIn('flip must be True',json.dumps(diagnostic['errors']))
            self.assertEqual(json.loads(diagnostic['final_output'])['design']['mates'][-1]['flip'],False)
            self.assertNotIn('mock-private-reasoning',json.dumps(diagnostic))

    async def test_unsupported_effort_is_rejected_without_erasing_saved_max(self):
        with tempfile.TemporaryDirectory() as folder:
            store=max_store(folder);settings=store.read();settings['roles']['executor']['reasoning_effort']='medium'
            with self.assertRaises(UserFacingError):store.save(settings)
            self.assertEqual(store.read()['roles']['executor']['reasoning_effort'],'max')
