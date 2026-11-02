import json
from pathlib import Path
import tempfile
import unittest

from workbench.engine import WorkbenchEngine, JobStopped
from workbench.jobs import Job
from workbench.settings import UserFacingError
from workbench_support import configured_store, FakeMCP, ScriptedAPI


class WorkbenchEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_deepseek_compatible_chat_provider_uses_separate_role_models(self):
        with tempfile.TemporaryDirectory() as folder:
            store, mcp, api = configured_store(folder), FakeMCP(), ScriptedAPI()
            settings = store.read()
            settings["roles"]["planner"] = {"provider": "deepseek", "model": "deepseek-v4-pro"}
            settings["roles"]["executor"] = {"provider": "deepseek", "model": "deepseek-flash"}
            store.save(settings, {"deepseek": "sk-deepseek-test-not-real"})
            job = Job("读取SolidWorks版本", Path(folder)/"jobs")
            await WorkbenchEngine(store, mcp.session, api.model).run(job)
            self.assertEqual(job.phase, "completed")
            self.assertEqual(api.requests[0]["model"], "deepseek-v4-pro")
            self.assertEqual(api.requests[-1]["model"], "deepseek-flash")
            self.assertTrue(all("max_tokens" in item and "max_completion_tokens" not in item for item in api.requests))

    async def test_strong_planner_and_economical_executor_use_real_sdk_pipeline(self):
        with tempfile.TemporaryDirectory() as folder:
            store, mcp, api = configured_store(folder), FakeMCP(), ScriptedAPI()
            engine = WorkbenchEngine(store, mcp.session, api.model)
            job = Job("读取SolidWorks版本", Path(folder)/"jobs")
            await engine.run(job)
            self.assertEqual(job.phase, "completed")
            self.assertEqual(api.requests[0]["model"], "gpt-6.1-sol")
            self.assertTrue(all(item["model"] == "gpt-5.4-mini" for item in api.requests[1:]))
            self.assertGreaterEqual(sum(name == "solidworks_connect" for name, _ in mcp.calls), 2)
            self.assertNotIn("sk-test-placeholder", json.dumps(job.public()))

    async def test_missing_dimensions_stop_before_executor_or_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            store, mcp, api = configured_store(folder), FakeMCP(), ScriptedAPI(action="create", clarify=True)
            job = Job("画个盒子", Path(folder)/"jobs")
            await WorkbenchEngine(store, mcp.session, api.model).run(job)
            self.assertEqual(job.phase, "clarify")
            self.assertEqual(len(api.requests), 1)
            self.assertNotIn("solidworks_create_basic_part", [name for name, _ in mcp.calls])

    async def test_model_cannot_write_outside_job_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            store, mcp = configured_store(folder), FakeMCP()
            outside = Path(folder)/"existing-model.SLDPRT"
            api = ScriptedAPI(action="create", outside=outside)
            job = Job("建10毫米立方体", Path(folder)/"jobs")
            with self.assertRaises(UserFacingError):
                await WorkbenchEngine(store, mcp.session, api.model).run(job)
            self.assertFalse(outside.exists())
            self.assertNotIn("solidworks_create_basic_part", [name for name, _ in mcp.calls])

    async def test_model_claimed_success_without_actual_files_requires_review(self):
        with tempfile.TemporaryDirectory() as folder:
            store, mcp, api = configured_store(folder), FakeMCP(), ScriptedAPI(action="create")
            job = Job("建10毫米立方体", Path(folder)/"jobs")
            await WorkbenchEngine(store, mcp.session, api.model).run(job)
            self.assertEqual(job.phase, "review_required")
            self.assertIn("尚未完整生成", job.summary)

    async def test_write_failure_stops_sdk_instead_of_retrying_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            store, mcp, api = configured_store(folder), FakeMCP(), ScriptedAPI(action="create")
            mcp.fail_create = True
            job = Job("建10毫米立方体", Path(folder)/"jobs")
            with self.assertRaises(UserFacingError):
                await WorkbenchEngine(store, mcp.session, api.model).run(job)
            self.assertEqual(sum(name == "solidworks_create_basic_part" for name, _ in mcp.calls), 1)
            self.assertEqual(len(api.requests), 2)

    async def test_cancelled_job_does_not_start_models_or_mcp(self):
        with tempfile.TemporaryDirectory() as folder:
            store, mcp, api = configured_store(folder), FakeMCP(), ScriptedAPI()
            job = Job("读取连接", Path(folder)/"jobs")
            job.cancel.set()
            with self.assertRaises(JobStopped):
                await WorkbenchEngine(store, mcp.session, api.model).run(job)
            self.assertFalse(mcp.calls)
            self.assertFalse(api.requests)

    async def test_api_errors_never_echo_credential_in_settings_test(self):
        with tempfile.TemporaryDirectory() as folder:
            store, mcp, api = configured_store(folder), FakeMCP(), ScriptedAPI(api_error=401)
            result = await WorkbenchEngine(store, mcp.session, api.model).test_connections()
            self.assertFalse(result["ok"])
            text = json.dumps(result)
            self.assertIn("invalid_api_key", text)
            self.assertNotIn("sk-test-placeholder", text)


if __name__ == "__main__":
    unittest.main()
