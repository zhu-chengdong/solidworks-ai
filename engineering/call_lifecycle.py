"""Keep the client alive for the full lifetime of a native COM operation."""
from concurrent.futures import TimeoutError


def wait_for_native_result(future,soft_timeout=180,on_wait=None):
    try:return future.result(timeout=soft_timeout)
    except TimeoutError:
        # result() also propagates TimeoutError raised by the operation itself.
        if future.done():return future.result()
        if on_wait is not None:on_wait()
        # COM has no safe cancellation here. Returning would permit the stdio
        # client to terminate its server while SolidWorks is still using it.
        return future.result()
