import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from workbench.magpie import (DEFAULT,MODELSCOPE,GATEWAY,MagpieService,validate_config,classify_task,route_profiles)
from workbench.settings import UserFacingError
from workbench.jobs import Job
from workbench.engine import model_settings
from workbench_support import configured_store


class MagpieTests(unittest.TestCase):
    def test_assembly_and_image_context_never_use_basic_pool(self):
        self.assertEqual(classify_task('报告实际软件版本')['tier'],'simple')
        self.assertEqual(classify_task('创建立方体后组装配合')['tier'],'complex')
        self.assertEqual(classify_task('孔径改到6毫米',prior_design={'document':'assembly'})['tier'],'complex')
        self.assertEqual(classify_task('按图生成',images=True)['tier'],'complex')
        self.assertEqual(classify_task('建立安装孔板并核查壁厚')['tier'],'standard')

    def test_free_only_and_explicit_model_contract_cannot_be_bypassed(self):
        for value in ({**DEFAULT,'free_only':False},{**DEFAULT,'enabled':True},
                      {**DEFAULT,'models':{'simple':'https://paid.invalid','standard':'','complex':''}},
                      {**DEFAULT,'max_output_tokens':True},{**DEFAULT,'max_output_tokens':999999}):
            with self.assertRaises(UserFacingError):validate_config(value)

    def service(self,root):
        store=configured_store(root);service=MagpieService(store,'http://127.0.0.1:8767')
        self.addCleanup(service.close)
        return store,service

    def config(self):return {**DEFAULT,'enabled':True,'models':{'simple':'Qwen/basic','standard':'Qwen/standard','complex':'Qwen/complex'},'effort':'max','max_output_tokens':65536}

    def test_saved_real_credential_never_enters_config_or_public_state(self):
        with tempfile.TemporaryDirectory() as folder:
            store,service=self.service(folder);secret='test-modelscope-private-credential'
            result=service.save({'key':secret,'config':self.config()})
            self.assertTrue(result['key_present'])
            self.assertNotIn(secret,json.dumps(result));self.assertNotIn(secret,(service.home/'integration.json').read_text())
            self.assertEqual(store.vault.get('modelscope',MODELSCOPE),secret)

    def test_profile_routes_all_roles_to_free_gateway_without_paid_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            store,service=self.service(folder);service.save({'key':'test-local-token','config':self.config()})
            job=Job('支架、轴和孔板装配体',Path(folder)/'jobs')
            planner,executor=route_profiles(store,job)
            self.assertEqual(planner['model'],'sw-modelscope/Qwen/complex');self.assertEqual(executor['model'],'sw-modelscope/Qwen/standard')
            for profile in (planner,executor,job._reviewer_profile):
                self.assertEqual(profile['base_url'],GATEWAY);self.assertTrue(profile['free_only'])
                actual=model_settings(profile,'executor');self.assertEqual(actual.extra_args['max_tokens'],65536);self.assertEqual(actual.reasoning.effort,'max')
            self.assertNotIn('test-local-token',json.dumps(job.public()))

    def test_disabled_route_keeps_original_roles_and_missing_free_key_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            store,service=self.service(folder);job=Job('读取版本',Path(folder)/'jobs')
            self.assertIsNone(route_profiles(store,job))
            service.save({'config':self.config()})
            with self.assertRaises(UserFacingError):route_profiles(store,job)

    def test_bridge_rejects_wrong_key_and_unlisted_models_without_upstream_call(self):
        with tempfile.TemporaryDirectory() as folder:
            store,service=self.service(folder);service.save({'key':'test-local-token','config':self.config()})
            with patch.object(service,'_json') as upstream:
                with self.assertRaises(UserFacingError):service.forward(b'{}','Bearer wrong')
                with self.assertRaises(UserFacingError):service.forward(json.dumps({'model':'paid/model'}).encode(),'Bearer '+service.bridge_key)
                upstream.assert_not_called()

    def test_bridge_uses_only_fixed_modelscope_host_and_memory_key(self):
        with tempfile.TemporaryDirectory() as folder:
            store,service=self.service(folder);service.save({'key':'test-local-token','config':self.config()})
            body={'model':'Qwen/complex','messages':[{'role':'user','content':'native test'}],'reasoning_effort':'max','max_tokens':65536}
            with patch.object(service,'_json',return_value={'choices':[]}) as upstream:
                service.forward(json.dumps(body).encode(),'Bearer '+service.bridge_key)
                args,kwargs=upstream.call_args
                self.assertEqual(args[0],MODELSCOPE+'/chat/completions');self.assertEqual(kwargs['key'],'test-local-token')
                self.assertEqual(kwargs['data'],body)

    def test_gateway_cannot_silently_lower_max_or_remove_output_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            store,service=self.service(folder);service.save({'key':'test-local-token','config':self.config()})
            for body in ({'model':'Qwen/complex','reasoning_effort':'none','max_tokens':65536},
                         {'model':'Qwen/complex','reasoning_effort':'max'},
                         {'model':'Qwen/complex','reasoning_effort':'max','max_tokens':131072}):
                with patch.object(service,'_json') as upstream:
                    with self.assertRaises(UserFacingError):service.forward(json.dumps(body).encode(),'Bearer '+service.bridge_key)
                    upstream.assert_not_called()

    def test_unknown_balance_is_not_displayed_as_zero_or_free_credit(self):
        with tempfile.TemporaryDirectory() as folder:
            store,service=self.service(folder);service.save({'key':'test-local-token','config':DEFAULT})
            with patch.object(service,'_json',return_value={'data':{}}):result=service.refresh()
            self.assertIsNone(result['balance']);self.assertEqual(result['balance_state'],'unknown')

    def test_empty_magpie_accounts_do_not_claim_successful_checkin(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            store,service=self.service(folder);service.proc=SimpleNamespace(poll=lambda:None,terminate=lambda:None,wait=lambda timeout:None)
            with patch.object(service,'_json',return_value=[]),patch.object(service,'cli') as cli:
                result=service.checkin();cli.assert_not_called()
            self.assertEqual(result['checkin']['state'],'not_configured')

class MagpiePaidGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_test_button_cannot_spend_paid_keys_when_free_pool_enabled(self):
        from workbench.engine import WorkbenchEngine
        with tempfile.TemporaryDirectory() as folder:
            store=configured_store(folder);service=MagpieService(store,'http://127.0.0.1:8767')
            try:
                service.save({'key':'test-private-modelscope','config':{**DEFAULT,'enabled':True,'models':{'simple':'Qwen/test','standard':'Qwen/test','complex':'Qwen/test'}}})
                with patch('workbench.engine.model_session') as models:
                    result=await WorkbenchEngine(store,model_factory=models).test_connections()
                    models.assert_not_called();self.assertFalse(result['ok']);self.assertIn('未调用',result['results'][0]['message'])
            finally:service.close()
