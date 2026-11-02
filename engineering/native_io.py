"""Native save/copy with explicit document identity and durable call evidence."""
import json,time
from pathlib import Path


def _run_save(app,doc,target,copy=False):
    import pythoncom,win32com.client
    from scripts.sw_connect import get_com_member as get,create_empty_dispatch_variant
    from scripts.sw_assembly import _activate_model_document
    from solidworks_mcp.automation.com_utils import resolve_solidworks_constant as constant
    target=Path(target).resolve();source=str(get(doc,'GetPathName'))
    same=bool(source) and Path(source).resolve()==target
    if target.exists() and not same:raise ValueError('An existing native file cannot be replaced')
    if copy and (not source or same):raise ValueError('Copy needs a saved source and a distinct new destination')
    target.parent.mkdir(parents=True,exist_ok=True)
    _activate_model_document(app,doc)
    active=app.ActiveDoc
    if active is None or str(get(active,'GetTitle'))!=str(get(doc,'GetTitle')) or str(get(active,'GetPathName'))!=source:
        raise RuntimeError('Native save target was not activated')
    doc.ClearSelection2(True)
    api='Save3' if same and not copy else 'IModelDocExtension.SaveAs3'
    options=constant('swSaveAsOptions_Silent')|(constant('swSaveAsOptions_Copy') if copy else 0)
    pid=int(get(app,'GetProcessID'))
    log=target.with_suffix('.native-io.jsonl')
    def record(event,**extra):
        with log.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'time':time.time(),'event':event,'pid':pid,'api':api,'source':source,'target':str(target),'copy':copy,'options':options,**extra},ensure_ascii=False)+'\n');stream.flush()
    errors=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    warnings=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    record('started')
    try:
        if api=='Save3':success=doc.Save3(options,errors,warnings)
        else:
            extension=win32com.client.dynamic.DumbDispatch(doc.Extension._oleobj_,'ModelDocExtension')
            success=extension.SaveAs3(str(target),0,options,create_empty_dispatch_variant(),create_empty_dispatch_variant(),errors,warnings)
        actual=str(get(doc,'GetPathName'))
        identity_ok=(actual==source) if copy else Path(actual).resolve()==target
        if not success or errors.value or not identity_ok or not target.is_file() or not target.stat().st_size:
            raise RuntimeError(f'Native {api} failed readback: errors={errors.value}, warnings={warnings.value}, identity={identity_ok}')
        record('returned',errors=errors.value,warnings=warnings.value,actual_path=actual,identity_verified=True)
        return True
    except Exception as exc:
        record('failed',error_type=type(exc).__name__,hresult=getattr(exc,'hresult',None))
        raise


def save_native_document(app,doc,path=None):
    from scripts.sw_connect import get_com_member as get
    target=path or str(get(doc,'GetPathName'))
    if not target:raise ValueError('A new native document needs a unique output path')
    return _run_save(app,doc,target)


def save_native_copy(app,doc,path):
    return _run_save(app,doc,path,copy=True)
