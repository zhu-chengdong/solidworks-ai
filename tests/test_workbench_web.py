import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from workbench.jobs import JobManager
from workbench.engine import WorkbenchEngine
from workbench.settings import SettingsStore, UserFacingError
from workbench.webserver import WorkbenchServer
from workbench_support import MemoryVault


class SettingsTests(unittest.TestCase):
    def test_keys_only_enter_vault_and_stay_out_of_disk_and_public_state(self):
        with tempfile.TemporaryDirectory() as folder:
            vault = MemoryVault()
            store = SettingsStore(folder, vault)
            secret = "sk-unit-credential-never-real"
            result = store.save(store.read(), {"openai": secret})
            self.assertTrue(result["providers"]["openai"]["key_present"])
            self.assertNotIn(secret, store.path.read_text(encoding="utf-8"))
            self.assertNotIn(secret, json.dumps(result))
            vault.remove("openai", result["providers"]["openai"]["base_url"])
            self.assertFalse(store.public()["providers"]["openai"]["key_present"])

    def test_changing_custom_endpoint_does_not_reuse_previous_key(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(folder, MemoryVault())
            settings = store.read()
            settings["providers"]["custom"]["base_url"] = "https://example.invalid/v1"
            store.save(settings, {"custom": "test-only"})
            settings["providers"]["custom"]["base_url"] = "https://another.invalid/v1"
            self.assertFalse(store.save(settings)["providers"]["custom"]["key_present"])

    def test_remote_plain_http_and_key_urls_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(folder, MemoryVault())
            for url in ("http://example.invalid/v1", "https://user:secret@example.invalid/v1", "https://example.invalid/v1?key=secret"):
                settings = store.read()
                settings["providers"]["custom"]["base_url"] = url
                with self.assertRaises(UserFacingError):
                    store.save(settings)


class WebTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = SettingsStore(Path(self.directory.name)/"settings", MemoryVault())
        self.engine = WorkbenchEngine(self.store)
        self.manager = JobManager(self.engine, Path(self.directory.name)/"jobs")
        self.server = WorkbenchServer(("127.0.0.1", 0), self.store, self.manager)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.manager.pool.shutdown(wait=True)
        self.directory.cleanup()

    def request(self, method, path, data=None, token=None, origin=None, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if token is not None: headers["X-App-Token"] = token
        if origin is not None: headers["Origin"] = origin
        if host is not None: headers["Host"] = host
        connection.request(method, path, body=json.dumps(data).encode() if data is not None else None, headers=headers)
        response = connection.getresponse()
        result = (response.status, response.read(), dict(response.headers))
        connection.close()
        return result

    def test_ui_and_health_are_served_without_credentials(self):
        status, body, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("把设计需求直接告诉我", body.decode())
        self.assertNotIn("__APP_TOKEN__", body.decode())
        self.assertIn("Content-Security-Policy", headers)
        self.assertEqual(self.request("GET", "/health")[0], 200)

    def test_drawing_example_is_a_real_dimensioned_dxf_without_credentials(self):
        import io,ezdxf
        status,body,headers=self.request('GET','/api/drawing-example')
        self.assertEqual(status,200);self.assertIn('attachment',headers['Content-Disposition'])
        drawing=ezdxf.read(io.StringIO(body.decode('utf8')))
        self.assertEqual(drawing.units,4);self.assertGreaterEqual(len(drawing.modelspace().query('DIMENSION')),6)
        self.assertEqual(len(drawing.modelspace().query('LEADER')),5)
        self.assertIn(b'FLAT BOTTOM',body)
        from drawing2cad.parser import inspect_dxf,select_spec,options
        for kind,count in [('sloped',4),('curved',3)]:
            status,body,headers=self.request('GET','/api/drawing-example?kind='+kind)
            self.assertEqual(status,200)
            path=Path(self.directory.name)/(kind+'.dxf');path.write_bytes(body)
            spec,question=select_spec(inspect_dxf(path),options('按三视图和孔标注建模'))
            self.assertIsNone(question,question);self.assertEqual(len(spec['holes']),count)
        self.assertEqual(self.request('GET','/api/drawing-example?kind=invalid')[0],400)

    def test_another_instance_cannot_share_our_listening_port(self):
        with self.assertRaises(OSError):
            WorkbenchServer(('127.0.0.1', self.server.server_port), self.store, self.manager)

    def test_mutations_require_app_token_and_local_origin(self):
        self.assertEqual(self.request("POST", "/api/settings", {})[0], 403)
        self.assertEqual(self.request("POST", "/api/settings", {}, self.server.token, "https://untrusted.invalid")[0], 403)
        self.assertEqual(self.request("GET", "/api/state", host="untrusted.invalid")[0], 403)

    def test_saved_key_never_returns_in_http_response(self):
        secret = "sk-local-test-placeholder"
        status, body, _ = self.request("POST", "/api/settings", {"settings": self.store.read(), "keys": {"openai": secret}}, self.server.token)
        self.assertEqual(status, 200)
        self.assertNotIn(secret.encode(), body)
        self.assertNotIn(secret.encode(), self.request("GET", "/api/state")[1])

    def test_magpie_key_entry_is_authenticated_and_key_never_returns(self):
        from workbench.magpie import DEFAULT
        secret='test-private-modelscope-input'
        payload={'action':'save','config':DEFAULT,'key':secret}
        self.assertEqual(self.request('POST','/api/magpie',payload)[0],403)
        status,body,_=self.request('POST','/api/magpie',payload,self.server.token)
        self.assertEqual(status,200);self.assertNotIn(secret.encode(),body)
        self.assertNotIn(secret.encode(),self.request('GET','/api/state')[1])
        self.assertNotIn(secret,(self.server.magpie.home/'integration.json').read_text())
        self.assertEqual(self.request('POST','/api/magpie',{'action':'unknown'},self.server.token)[0],400)

    def test_task_without_keys_is_rejected_before_mcp(self):
        status, body, _ = self.request("POST", "/api/jobs", {"message": "建10毫米立方体"}, self.server.token)
        self.assertEqual(status, 400)
        self.assertFalse(self.manager.jobs)

    def test_static_path_traversal_is_not_served(self):
        self.assertEqual(self.request("GET", "/%2e%2e/agent.py")[0], 404)

    def test_local_cad_upload_is_authenticated_and_keeps_binary_out_of_response(self):
        raw=bytes.fromhex('D0CF11E0A1B11AE1')+b'fake-container-native-open-required'
        def upload(token):
            connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
            headers={'Content-Type':'application/octet-stream','X-File-Name':'plate.SLDPRT'}
            if token:headers['X-App-Token']=token
            connection.request('POST','/api/cad-uploads',body=raw,headers=headers)
            response=connection.getresponse();status=response.status;body=response.read();connection.close()
            return status,body
        self.assertEqual(upload(None)[0],403)
        status,body=upload(self.server.token);self.assertEqual(status,201)
        metadata=json.loads(body);self.assertEqual(metadata['name'],'plate.SLDPRT')
        self.assertNotIn(b'fake-container-native',body)
        source,_=self.server.cad_store.resolve([metadata['id']])[0]
        self.assertEqual(source.read_bytes(),raw)


if __name__ == "__main__":
    unittest.main()
