"""One COM apartment with an idle message pump and non-cancelling shutdown."""
import atexit,queue,threading
from concurrent.futures import Future


class StaExecutor:
    def __init__(self,cleanup=None):
        import win32event
        self._queue=queue.Queue();self._lock=threading.Lock();self._closed=False
        self._wake=win32event.CreateEvent(None,False,False,None)
        self._ready=threading.Event();self._cleanup=cleanup;self._startup_error=None
        self._thread=threading.Thread(target=self._run,name='SW2024-STA',daemon=True)
        self._thread.start();self._ready.wait()
        if self._startup_error is not None:raise self._startup_error
        atexit.register(self.shutdown)

    def submit(self,fn,*args,**kwargs):
        import win32event
        future=Future()
        with self._lock:
            if self._closed:raise RuntimeError('COM apartment has shut down')
            self._queue.put((future,fn,args,kwargs));win32event.SetEvent(self._wake)
        return future

    def _run(self):
        import pythoncom,win32event,win32con
        try:pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        except BaseException as exc:self._startup_error=exc;self._ready.set();return
        self._ready.set()
        try:
            while True:
                # Dispatch only this server thread's native COM traffic. No UI
                # selectors, injected input, window messages or CAD commands.
                pythoncom.PumpWaitingMessages()
                try:item=self._queue.get_nowait()
                except queue.Empty:
                    win32event.MsgWaitForMultipleObjects((self._wake,),False,100,win32con.QS_ALLINPUT)
                    continue
                if item is None:break
                future,fn,args,kwargs=item
                if future.set_running_or_notify_cancel():
                    try:result=fn(*args,**kwargs)
                    except BaseException as exc:future.set_exception(exc)
                    else:future.set_result(result)
                # Drop completed call frames on their owning COM thread.
                item=future=fn=args=kwargs=None
        finally:
            try:
                if self._cleanup is not None:self._cleanup()
                pythoncom.PumpWaitingMessages()
            finally:pythoncom.CoUninitialize()

    def shutdown(self,wait=True):
        import win32event
        with self._lock:
            if not self._closed:
                self._closed=True;self._queue.put(None);win32event.SetEvent(self._wake)
        if wait and threading.current_thread() is not self._thread:self._thread.join()
        if not self._thread.is_alive():atexit.unregister(self.shutdown)

    def __enter__(self):return self
    def __exit__(self,*_args):self.shutdown()
