import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import httpx2
from openai import AsyncOpenAI
from workbench.engine import WorkbenchEngine
from workbench.jobs import Job
from workbench_support import configured_store,FakeMCP,ScriptedAPI
from test_deepseek_max import MaxChatAPI

class HighestChatAPI(MaxChatAPI):
    def __init__(self):super().__init__();self.response_api=ScriptedAPI()
    def handle(self,request):
        body=json.loads(request.content)
        if request.url.path.endswith('/responses'):
            if body.get('max_output_tokens')!=128000 or body.get('reasoning',{}).get('effort')!='max':
                return httpx2.Response(400,json={'error':{'message':'Responses must preserve MAX and capacity'}})
            self.requests.append(body)
            return self.response_api.handle(request)
        if 'max_tokens' in body or body.get('max_completion_tokens')!=128000 or body.get('reasoning_effort')!='xhigh':
            return httpx2.Response(400,json={'error':{'message':'GPT-6 Chat requires max_completion_tokens and highest supported xhigh'}})
        response=super().handle(request);data=response.json();data['model']=body['model']
        return httpx2.Response(200,json=data)

class OpenAIHighestChat(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_highest_planning_and_tool_roundtrip_preserves_capacity_and_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            store=configured_store(folder);settings=store.read();settings['providers']['openai']['api_style']='chat_completions'
            settings['roles']['planner']={'provider':'openai','model':'gpt-6.1-sol','vision':True,'reasoning_effort':'max'}
            settings['roles']['executor']={'provider':'openai','model':'gpt-6.1-terra','reasoning_effort':'max'};store.save(settings,{})
            job=Job('只读连接',Path(folder)/'jobs');api=HighestChatAPI();mcp=FakeMCP()
            def client(**kwargs):return AsyncOpenAI(**kwargs,http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api.handle)))
            with patch('workbench.engine.AsyncOpenAI',side_effect=client):await WorkbenchEngine(store,session_factory=mcp.session).run(job)
            self.assertEqual(job.phase,'completed');self.assertEqual(len(api.requests),3)
            self.assertEqual([r['model'] for r in api.requests],['gpt-6.1-sol','gpt-6.1-terra','gpt-6.1-terra'])
            self.assertEqual(job.usage,{'input_tokens':60,'output_tokens':70})
            responses=[e for e in job.events if e['kind']=='model_response']
            self.assertEqual(len(responses),3)
            self.assertEqual([e['reasoning_effort'] for e in responses],['xhigh','max','max'])
            self.assertTrue(all(e['max_output_tokens']==128000 for e in responses))
            self.assertTrue(any(e['kind']=='model_transport' and e['api_style']=='responses' for e in job.events))
            self.assertFalse(any(name.startswith('solidworks_create') for name,_ in mcp.calls))
            self.assertNotIn('mock-private-reasoning',json.dumps(job.public()))

if __name__=='__main__':unittest.main()
