"""Dependency-isolated harness process using JSON-lines tool RPC.

The parent enforces scope and call budgets. This isolates SDK dependencies,
not hostile code: plugins and interpreters must be trusted. On POSIX systems
the entire worker process group is terminated on cancellation or completion.
"""

import asyncio
import inspect
import json
import os
import signal
import sys
from dataclasses import asdict

from cognition.domain import Capabilities, Proposal, Request
from cognition.harnesses.base import ModelSettings
from cognition.harnesses.errors import HarnessFailure
from cognition.layers.cognitive.tools import Tools


async def stop_worker(child: asyncio.subprocess.Process) -> None:
    """Stop native SDK descendants as well as their Python worker."""
    if sys.platform != "win32":
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    elif child.returncode is None:
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(child.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
        if killer.returncode and child.returncode is None:
            child.terminate()
    if child.returncode is None:
        try:
            await asyncio.wait_for(child.wait(), 2)
        except TimeoutError:
            if sys.platform != "win32":
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                child.kill()
            await child.wait()


class ProcessHarness:
    def __init__(self, name: str, interpreter: str, settings: ModelSettings) -> None:
        self.name, self.interpreter, self.settings = name, interpreter, settings

    def capabilities(self) -> Capabilities:
        return Capabilities(
            name=self.name,
            live_model=self.name != "reference",
            streaming=self.name == "antigravity",
            cancellation="process group on POSIX; process tree on Windows",
        )

    async def propose(self, request: Request, tools: Tools) -> Proposal:
        env = os.environ.copy()
        env["GOOGLE_GENAI_USE_VERTEXAI"] = str(self.settings.vertex).lower()
        env["GOOGLE_CLOUD_PROJECT"] = self.settings.project
        env["GOOGLE_CLOUD_LOCATION"] = self.settings.location
        key = env.get("GOOGLE_API_KEY") or env.get("GEMINI_API_KEY")
        if key:
            env["GOOGLE_API_KEY"] = env["GEMINI_API_KEY"] = key
        child = await asyncio.create_subprocess_exec(
            self.interpreter,
            "-m",
            "cognition.harnesses.worker",
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=1024 * 1024,
            start_new_session=sys.platform != "win32",
        )
        assert child.stdin is not None and child.stdout is not None
        stdin, stdout = child.stdin, child.stdout
        approved = {fn.__name__: fn for fn in tools.functions()}

        async def send(value: dict) -> None:
            stdin.write((json.dumps(value) + "\n").encode())
            await stdin.drain()

        try:
            await send(
                {
                    "name": self.name,
                    "settings": asdict(self.settings),
                    "request": request.model_dump(mode="json"),
                    "tool_names": list(approved),
                }
            )
            streamed = 0
            for _ in range(10000):
                line = await stdout.readline()
                if not line:
                    raise RuntimeError("Harness worker exited without proposal")
                message = json.loads(line)
                if message["type"] == "stream":
                    text = message["text"]
                    if not isinstance(text, str):
                        raise RuntimeError("Invalid stream message")
                    streamed += len(text)
                    if streamed > 50000:
                        raise RuntimeError("Worker stream budget exhausted")
                    tools.emit(text)
                    continue
                if message["type"] == "result":
                    return Proposal.model_validate(message["proposal"])
                if message["type"] == "error":
                    raise HarnessFailure(message.get("code", "runtime"))
                if message["type"] != "tool":
                    raise RuntimeError("Harness worker failed or sent invalid message")
                try:
                    result = approved[message["name"]](**message["args"])
                    if inspect.isawaitable(result):
                        result = await result
                    await send({"value": result})
                except Exception as exc:
                    await send({"error": type(exc).__name__})
            raise RuntimeError("Worker message budget exhausted")
        finally:
            await stop_worker(child)
