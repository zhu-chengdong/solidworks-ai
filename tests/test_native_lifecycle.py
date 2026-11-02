import asyncio,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from engineering.call_lifecycle import wait_for_native_result
from workbench.native_wait import call_native


class NativeLifetimeTests(unittest.TestCase):
    def test_soft_timeout_cannot_report_finished_while_native_call_is_still_running(self):
        entered=threading.Event();release=threading.Event();waiting=threading.Event();received=[]
        def native():entered.set();release.wait(2);return 'native-finished'
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(native);self.assertTrue(entered.wait(1))
            thread=threading.Thread(target=lambda:received.append(wait_for_native_result(future,.01,waiting.set)))
            thread.start()
            try:
                waiting.wait(.15)
                self.assertEqual(received,[],'Old behavior ends the request and permits MCP process teardown before COM returns')
                self.assertFalse(future.cancelled())
            finally:release.set();thread.join(1)
            self.assertEqual(received,['native-finished'])

    def test_operation_own_timeout_is_propagated_instead_of_masked_as_wait_timeout(self):
        with ThreadPoolExecutor(max_workers=1) as pool:
            def native():raise TimeoutError('native mutex did not enter operation')
            future=pool.submit(native)
            with self.assertRaisesRegex(TimeoutError,'native mutex'):wait_for_native_result(future,1)


class NativeClientDrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_notice_does_not_cancel_the_call(self):
        release=asyncio.Event();events=[]
        class Job:
            def event(self,*args,**kwargs):events.append(args[0])
        class Session:
            async def call_tool(self,*args):await release.wait();return 'finished'
        task=asyncio.create_task(call_native(Job(),Session(),'native',{},.01))
        await asyncio.sleep(.035);self.assertFalse(task.done());self.assertIn('cad_wait',events)
        release.set();self.assertEqual(await task,'finished')

    async def test_outer_cancellation_drains_accepted_call_before_session_teardown(self):
        release=asyncio.Event();entered=asyncio.Event();finished=[]
        class Job:
            def event(self,*args,**kwargs):pass
        class Session:
            async def call_tool(self,*args):entered.set();await release.wait();finished.append(True)
        task=asyncio.create_task(call_native(Job(),Session(),'native',{},.01))
        await entered.wait();task.cancel();await asyncio.sleep(.01)
        self.assertFalse(task.done());self.assertEqual(finished,[])
        release.set()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(finished,[True])
