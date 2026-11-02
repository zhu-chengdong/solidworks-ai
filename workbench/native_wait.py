"""Soft progress deadlines must not tear down an executing native MCP call."""
import asyncio


async def call_native(job,session,name,args,notice_seconds=30):
    pending=asyncio.create_task(session.call_tool(name,args))
    try:
        while True:
            done,_=await asyncio.wait({pending},timeout=notice_seconds)
            if done:return pending.result()
            job.event('cad_wait','SolidWorks尚未返回，保持原生连接；停止将在本阶段返回后生效。',tool=name)
    except asyncio.CancelledError:
        # A normal Stop only sets job.cancel. If an outer task is cancelled,
        # still drain the accepted COM call before leaving the MCP context.
        await asyncio.shield(pending)
        raise
