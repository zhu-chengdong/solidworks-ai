"""Read native Windows commit headroom before opening new CAD documents."""
def memory_status():
    import ctypes
    from ctypes import wintypes
    class MemoryStatus(ctypes.Structure):
        _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD)]+[(name,ctypes.c_ulonglong) for name in ('total_physical','available_physical','total_commit','available_commit','total_virtual','available_virtual','extended')]
    status=MemoryStatus();status.length=ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):raise ctypes.WinError()
    return {name:int(getattr(status,name)) for name in ('total_physical','available_physical','total_commit','available_commit')}

def require_headroom(status,opening=False):
    minimum=(3 if opening else 1)*1024**3
    if status['available_commit']<minimum or status['available_physical']<768*1024**2:
        raise ValueError('系统可提交内存不足，原生出图已在新写入前停止。当前可提交余量约'+str(round(status['available_commit']/1024**3,2))+' GB。请先释放本机资源后新建任务。')
