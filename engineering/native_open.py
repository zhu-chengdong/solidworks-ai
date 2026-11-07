"""Silent native document opening with durable, safe call-boundary evidence."""
import json,time
from pathlib import Path


def _get(obj,name,*args):
    from scripts.sw_connect import get_com_member
    return get_com_member(obj,name,*args)


def _open6(app,path,kind,options,errors,warnings):
    import win32com.client
    # One known native IDispatch signature, rather than retrying a partially
    # bound makepy call with a second invocation.
    native=win32com.client.dynamic.DumbDispatch(app._oleobj_,'SldWorks.Application')
    return native.OpenDoc6(str(path),kind,options,'',errors,warnings)


def open_native_document(app,file_path,read_only=False,silent=True,raise_on_error=True):
    import pythoncom,win32com.client
    get=_get
    path=Path(file_path).resolve();kinds={'.sldprt':1,'.sldasm':2,'.slddrw':3}
    if not path.is_file() or path.suffix.lower() not in kinds:raise ValueError('Native open requires an existing SLDPRT/SLDASM/SLDDRW')
    if not silent or not raise_on_error:raise ValueError('This native drawing route requires silent opening and explicit failures')
    log=path.with_suffix('.native-open.jsonl');started=time.monotonic()
    def record(event,**fields):
        with log.open('a',encoding='utf8') as stream:
            stream.write(json.dumps({'time':time.time(),'event':event,'path':str(path),
                'elapsed_seconds':time.monotonic()-started,**fields},ensure_ascii=False)+'\n');stream.flush()
    record('lookup_started')
    try:
        existing=app.GetOpenDocumentByName(str(path));record('lookup_returned',already_open=existing is not None)
        if existing is not None:model=existing
        else:
            errors=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
            warnings=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
            options=1|(2 if read_only else 0)
            record('OpenDoc6_started',options=options,pid=int(get(app,'GetProcessID')))
            model=_open6(app,path,kinds[path.suffix.lower()],options,errors,warnings)
            if isinstance(model,(tuple,list)):
                values=list(model);model=values[0] if values else None
                if len(values)>1 and values[1] is not None:errors.value=int(values[1])
                if len(values)>2 and values[2] is not None:warnings.value=int(values[2])
            record('OpenDoc6_returned',errors=errors.value,warnings=warnings.value,document_returned=model is not None)
            if model is None or errors.value:raise RuntimeError('Native OpenDoc6 did not return a verified document; no open replayed')
        if Path(str(get(model,'GetPathName'))).resolve()!=path or int(get(model,'GetType'))!=kinds[path.suffix.lower()]:
            raise RuntimeError('Native document path/type changed during opening')
        record('identity_verified');return model
    except Exception as exc:
        record('failed',error_type=type(exc).__name__,hresult=getattr(exc,'hresult',None));raise
