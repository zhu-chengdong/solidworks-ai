import sys,threading,time,unittest


@unittest.skipUnless(sys.platform=='win32','Native COM apartment tests require Windows')
class StaExecutorTests(unittest.TestCase):
    def test_idle_owner_dispatches_real_cross_apartment_callback(self):
        import pythoncom
        from win32com.server.util import wrap
        from win32com.client.dynamic import DumbDispatch
        from engineering.sta_executor import StaExecutor
        class Echo:
            _public_methods_=['Echo']
            def Echo(self,value):return value+1
        owned={};done=threading.Event();answer=[];errors=[]
        with StaExecutor() as pool:
            def create():
                owned['object']=wrap(Echo())
                return pythoncom.CoMarshalInterThreadInterfaceInStream(pythoncom.IID_IDispatch,owned['object'])
            stream=pool.submit(create).result(2)
            def client():
                pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
                try:
                    dispatch=DumbDispatch(pythoncom.CoGetInterfaceAndReleaseStream(stream,pythoncom.IID_IDispatch))
                    answer.append(dispatch.Echo(7));dispatch=None
                except BaseException as exc:errors.append(exc)
                finally:pythoncom.CoUninitialize();done.set()
            worker=threading.Thread(target=client);worker.start()
            try:self.assertTrue(done.wait(2),'Idle STA must service callbacks without a submitted pump job')
            finally:
                # A regression must still release the test's accepted COM call.
                if not done.is_set():pool.submit(pythoncom.PumpWaitingMessages).result(2)
                worker.join(2);pool.submit(owned.clear).result(2)
            self.assertFalse(errors);self.assertEqual(answer,[8])

    def test_operations_and_cleanup_share_one_owner_and_keep_order(self):
        from engineering.sta_executor import StaExecutor
        cleaned=[];rows=[]
        with StaExecutor(cleanup=lambda:cleaned.append(threading.get_ident())) as pool:
            futures=[pool.submit(lambda i=i:rows.append((i,threading.get_ident()))) for i in range(8)]
            for f in futures:f.result(2)
        self.assertEqual([r[0] for r in rows],list(range(8)))
        self.assertEqual(set(r[1] for r in rows),set(cleaned))
        with self.assertRaises(RuntimeError):pool.submit(lambda:None)

    def test_shutdown_drains_accepted_call_without_cancelling(self):
        from engineering.sta_executor import StaExecutor
        release=threading.Event();entered=threading.Event();pool=StaExecutor()
        future=pool.submit(lambda:(entered.set(),release.wait(2),'done')[-1])
        self.assertTrue(entered.wait(1));closer=threading.Thread(target=pool.shutdown);closer.start()
        try:
            time.sleep(.03);self.assertTrue(closer.is_alive());self.assertFalse(future.cancelled())
        finally:release.set();closer.join(2)
        self.assertEqual(future.result(1),'done')

    def test_queued_cancel_does_not_execute_cad_work(self):
        from engineering.sta_executor import StaExecutor
        release=threading.Event();entered=threading.Event();rows=[]
        with StaExecutor() as pool:
            first=pool.submit(lambda:(entered.set(),release.wait(2)))
            self.assertTrue(entered.wait(1));queued=pool.submit(lambda:rows.append('unexpected'))
            self.assertTrue(queued.cancel());release.set();first.result(2)
        self.assertEqual(rows,[])
