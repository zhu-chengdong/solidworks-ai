import sys,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import patch

@unittest.skipUnless(sys.platform=='win32','Native document VARIANT requires Windows')
class NativeOpenTests(unittest.TestCase):
    def invoke(self,app,path,open6):
        from engineering.native_open import open_native_document
        def get(obj,name,*args):return getattr(obj,name)(*args)
        with patch('engineering.native_open._get',side_effect=get),patch('engineering.native_open._open6',side_effect=open6) as native:
            return open_native_document(app,path,read_only=True),native

    def test_exact_existing_document_is_reused_without_reopening(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'part.SLDPRT';path.write_bytes(b'test')
            doc=Obj(GetPathName=lambda:str(path),GetType=lambda:1)
            result,native=self.invoke(Obj(GetOpenDocumentByName=lambda p:doc),path,None)
            self.assertIs(result,doc);native.assert_not_called()

    def test_read_only_open_uses_one_silent_call_and_records_its_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'part.SLDPRT';path.write_bytes(b'test')
            doc=Obj(GetPathName=lambda:str(path),GetType=lambda:1)
            app=Obj(GetOpenDocumentByName=lambda p:None,GetProcessID=lambda:123)
            result,native=self.invoke(app,path,lambda app,p,kind,options,e,w:doc)
            self.assertIs(result,doc);self.assertEqual(native.call_count,1);self.assertEqual(native.call_args.args[3],3)
            records=[json.loads(line) for line in path.with_suffix('.native-open.jsonl').read_text(encoding='utf8').splitlines()]
            self.assertEqual([r['event'] for r in records],['lookup_started','lookup_returned','OpenDoc6_started','OpenDoc6_returned','identity_verified'])

    def test_native_failure_is_not_replayed_or_written_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'part.SLDPRT';path.write_bytes(b'test')
            app=Obj(GetOpenDocumentByName=lambda p:None,GetProcessID=lambda:123)
            from engineering.native_open import open_native_document
            def get(obj,name,*args):return getattr(obj,name)(*args)
            with patch('engineering.native_open._get',side_effect=get),patch('engineering.native_open._open6',side_effect=RuntimeError('private-error-details')) as native:
                with self.assertRaises(RuntimeError):open_native_document(app,path)
                self.assertEqual(native.call_count,1)
            log=path.with_suffix('.native-open.jsonl').read_text(encoding='utf8')
            self.assertNotIn('private-error-details',log);self.assertIn('"event": "failed"',log)

    def test_wrong_native_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'part.SLDPRT';path.write_bytes(b'test')
            doc=Obj(GetPathName=lambda:str(path.with_name('other.SLDPRT')),GetType=lambda:1)
            with self.assertRaisesRegex(RuntimeError,'path/type'):
                self.invoke(Obj(GetOpenDocumentByName=lambda p:doc),path,None)
