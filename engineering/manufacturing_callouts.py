"""Read official dual-interface hole variables through native vtables."""
from pathlib import Path
import math


def bridge_dispatch(existing):
    """Standard COM stream marshaling preserves the already connected object."""
    import ctypes,pythoncom
    from comtypes import IUnknown,GUID
    from comtypes.automation import IDispatch
    source=pythoncom.CreateStreamOnHGlobal()
    pythoncom.CoMarshalInterface(source,pythoncom.IID_IDispatch,existing._oleobj_,pythoncom.MSHCTX_INPROC,pythoncom.MSHLFLAGS_NORMAL)
    size=source.Seek(0,2);source.Seek(0,0);data=source.Read(size)
    memory=ctypes.create_string_buffer(data)
    create=ctypes.WinDLL('shlwapi').SHCreateMemStream
    create.argtypes=[ctypes.c_void_p,ctypes.c_uint];create.restype=ctypes.POINTER(IUnknown)
    stream=create(memory,len(data))
    if not stream:raise MemoryError('Cannot allocate native COM marshal stream')
    unmarshal=ctypes.OleDLL('ole32').CoUnmarshalInterface
    unmarshal.argtypes=[ctypes.c_void_p,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)]
    unmarshal.restype=ctypes.HRESULT
    output=ctypes.c_void_p()
    try:unmarshal(stream,ctypes.byref(IDispatch._iid_),ctypes.byref(output))
    except Exception:
        source.Seek(0,0);pythoncom.CoReleaseMarshalData(source);raise
    return ctypes.cast(output,ctypes.POINTER(IDispatch))


def read_variables(existing_app,document_path,raw_variables):
    import comtypes.client
    from integrations.czuryk.native_only import registered_executable
    module=comtypes.client.GetModule(str(registered_executable().parent/'sldworks.tlb'))
    from scripts.sw_connect import get_com_member as get
    model=get(existing_app,'ActiveDoc')
    if int(get(model,'GetType'))!=3 or Path(get(model,'GetPathName')).resolve()!=Path(document_path).resolve():
        raise RuntimeError('The native callout reader is not attached to the task drawing')
    if len(raw_variables)>128:raise ValueError('Native hole callout variable count exceeds the bounded limit')
    result=[]
    for raw in raw_variables:
        pointer=bridge_dispatch(raw)
        variable=pointer.QueryInterface(module.ICalloutVariable)
        row={'name':variable.VariableName,'type':int(variable.Type),'variable_type':int(variable.VariableType)}
        for interface,member,key in [(module.ICalloutLengthVariable,'Length','length_m'),(module.ICalloutAngleVariable,'Angle','angle_rad'),(module.ICalloutStringVariable,'String','string')]:
            try:
                value=getattr(pointer.QueryInterface(interface),member)
                if isinstance(value,float) and not math.isfinite(value):raise ValueError('Nonfinite native hole callout variable')
                row[key]=value;break
            except (ValueError,TypeError):raise
            except Exception:continue
        if not any(k in row for k in ('length_m','angle_rad','string')):raise RuntimeError('Hole callout variable value is unavailable')
        result.append(row)
    return result
