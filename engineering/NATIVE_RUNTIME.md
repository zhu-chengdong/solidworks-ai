# Native COM runtime and diagnostics

The server uses one dedicated single-threaded COM apartment for all CAD work,
plus a cross-process mutex. Its idle wait also dispatches incoming COM traffic.
It does not send input or messages to SOLIDWORKS windows.

An isolated native COM regression reproduced a definite defect in the previous
ThreadPoolExecutor owner: a callback into the idle apartment stayed blocked until
an extra pump task ran. The replacement StaExecutor services that callback while
idle, keeps CAD calls in FIFO order, drains accepted calls on shutdown, and releases
the cached application interface on its owning apartment before CoUninitialize.
See Microsoft's [STA requirements](https://learn.microsoft.com/en-us/windows/win32/com/single-threaded-apartments).

Manufacturing document opens record lookup, the actual OpenDoc6 call, its return
codes, PID, elapsed time and exact path/type readback in local native-open journals.
A native failure is not replayed. Errors record type/HRESULT rather than exception
arguments or local variables. Journals and private diagnostics are excluded from
releases and the normal delivery list.

During investigation, a fresh SOLIDWORKS2024 session opened the unchanged input
in approximately nine seconds. The historical process had subsequently crashed
in clr.dll; its local dump includes native UI/exception handling frames and does
not prove that the apartment defect caused that crash. The dump is kept locally,
and no global accessibility, add-in, or system setting is disabled as a workaround.

Qualification requires actual native part/drawing open-close cycles, drawing
save/reopen and PDF checks, then the packaged application workflow. A passing
mock or generic COM test alone is not SOLIDWORKS acceptance.

Assembly-drawing qualification also checks available Windows commit before
opening new documents. Free physical RAM alone is insufficient evidence of
allocation headroom. Test-owned copies accumulated during development; closing
only their enumerated native documents released about4.9GiB of private commit.
The new path saves owned references through the active assembly without opening
every child graphics window and closes its saved task documents after delivery.

A read-only Python stack sample isolated another wait to SciPy BLAS DLL loading
on the CAD STA, with no outstanding SolidWorks COM call. Only that Python test
service was ended; the CAD process was preserved. Balloon assignment now uses a
bounded pure-Python algorithm, so no new scientific DLL is loaded in that call.
Keep private process/stack diagnostics out of release archives.
