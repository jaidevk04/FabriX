import asyncio
import sys

from cognition.harnesses.process import stop_worker


async def test_worker_cleanup_stops_descendant_listener():
    listener = (
        "import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); "
        "s.listen(); print(s.getsockname()[1],flush=True); time.sleep(60)"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-u','-c',{listener!r}],stdout=sys.stdout); "
        "time.sleep(60)"
    )
    worker = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        parent,
        stdout=asyncio.subprocess.PIPE,
        start_new_session=sys.platform != "win32",
    )
    try:
        assert worker.stdout is not None
        port = int(await asyncio.wait_for(worker.stdout.readline(), 10))
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await writer.wait_closed()
        await stop_worker(worker)
        await asyncio.wait_for(worker.wait(), 5)
        try:
            _, remaining = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            pass
        else:
            remaining.close()
            await remaining.wait_closed()
            raise AssertionError("SDK descendant is still running after worker cleanup")
    finally:
        if worker.returncode is None:
            await stop_worker(worker)
