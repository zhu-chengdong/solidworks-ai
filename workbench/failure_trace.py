"""Keep diagnostic locations without serializing exception values or locals."""
from pathlib import Path
import traceback


def failure_trace(exc):
    seen = set()
    def visit(error):
        if id(error) in seen:
            return None
        seen.add(id(error))
        record = {"type": type(error).__name__, "frames": [
            {"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
            for frame in traceback.extract_tb(error.__traceback__)[-16:]]}
        for name in ("errno", "winerror"):
            value = getattr(error, name, None)
            if type(value) is int:
                record[name] = value
        cause = error.__cause__ or error.__context__
        if cause is not None:
            record["cause"] = visit(cause)
        if isinstance(error, BaseExceptionGroup):
            record["exceptions"] = [visit(item) for item in error.exceptions[:8]]
        return record
    return visit(exc)
