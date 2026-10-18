"""Trusted worker entry point. Stdout carries RPC, never SDK logging."""

import asyncio
import json
import sys
from contextlib import redirect_stdout
from threading import Lock
from typing import Any

from cognition.domain import Request
from cognition.harnesses.base import ModelSettings
from cognition.harnesses.errors import failure_code
from cognition.harnesses.factory import create
from cognition.layers.cognitive.tools import Tools


class Proxy(Tools):
    def __init__(self) -> None:
        self.output = sys.stdout
        self.rpc_lock = Lock()
        self.supported: list[str] = []

    def functions(self):
        from cognition.layers.cognitive.catalog import bind

        return [
            fn
            for fn in bind(
                self,
                specialist="delegate_specialist" in self.supported,
                cores="read_core_live" in self.supported,
            )
            if not self.supported or fn.__name__ in self.supported
        ]

    def read_layers(self) -> dict:
        return self.call("read_layers", {})

    def list_skills(self) -> list[dict]:
        return self.call("list_skills", {})

    def read_skill(self, name: str) -> dict:
        return self.call("read_skill", {"name": name})

    def read_skill_resource(self, name: str, path: str) -> dict:
        return self.call("read_skill_resource", {"name": name, "path": path})

    def read_industry_process(self, industry: str, tool_name: str) -> dict:
        return self.call(tool_name, {})

    def simulate_industry_action(self, industry: str, tool_name: str, value: float) -> dict:
        return self.call(tool_name, {"value": value})

    def read_core_live(self, core: str, scope: str = "", response_format: str = "concise") -> dict:
        return self.call(
            "read_core_live", {"core": core, "scope": scope, "response_format": response_format}
        )

    async def ask_core(self, core: str, question: str, response_format: str = "concise") -> dict:
        return self.call(
            "ask_core", {"core": core, "question": question, "response_format": response_format}
        )

    def read_core_reports(self) -> dict:
        return self.call("read_core_reports", {})

    def request_optimization(self, goal: str = "recovery", max_duty_change: float = 20.0) -> dict:
        return self.call("request_optimization", {"goal": goal, "max_duty_change": max_duty_change})

    def read_business(self) -> dict:
        return self.call("read_business", {})

    def read_kpis(self) -> dict:
        return self.call("read_kpis", {})

    def read_sustainability(self) -> dict:
        return self.call("read_sustainability", {})

    async def delegate_specialist(self, specialist_id: str, objective: str) -> dict:
        return self.call(
            "delegate_specialist", {"specialist_id": specialist_id, "objective": objective}
        )

    def emit(self, text: str) -> None:
        with self.rpc_lock:
            self.output.write(json.dumps({"type": "stream", "text": text}) + "\n")
            self.output.flush()

    def call(self, name: str, args: dict) -> Any:
        with self.rpc_lock:
            self.output.write(json.dumps({"type": "tool", "name": name, "args": args}) + "\n")
            self.output.flush()
            result = json.loads(sys.stdin.readline())
            if "error" in result:
                raise RuntimeError("Platform denied tool call")
            return result["value"]

    def discover(self, query: str = "") -> list[dict]:
        """Discover incident-approved connector, tool, role and control capabilities."""
        return self.call("discover", {"query": query})

    def read_snapshot(self) -> dict:
        """Read the immutable incident snapshot."""
        return self.call("read_snapshot", {})

    def read_time(self) -> dict:
        """Read simulated process time, wall-clock time and forecast horizon."""
        return self.call("read_time", {})

    def read_instruments(self) -> dict:
        """Read simulator-derived process instruments with units and bands."""
        return self.call("read_instruments", {})

    def forecast_instruments(self, value: float) -> dict:
        """Forecast instrument values over simulated time for a duty percent, on a twin copy."""
        return self.call("forecast_instruments", {"value": value})

    def read_control(self) -> dict:
        """Read permitted control bounds, units and change limits."""
        return self.call("read_control", {})

    def read_sop(self) -> dict:
        """Read operating procedures and recovery criteria."""
        return self.call("read_sop", {})

    def simulate_action(self, value: float) -> dict:
        """Predict a duty percentage on a twin copy without executing controls."""
        return self.call("simulate_action", {"value": value})


async def main() -> None:
    payload = json.loads(sys.stdin.readline())
    proxy = Proxy()
    proxy.supported = payload.get("tool_names", [])
    proxy.request = Request.model_validate(payload["request"])
    try:
        with redirect_stdout(sys.stderr):
            harness = create(payload["name"], ModelSettings(**payload["settings"]), isolated=False)
            proposal = await harness.propose(Request.model_validate(payload["request"]), proxy)
        result = {"type": "result", "proposal": proposal.model_dump(mode="json")}
    except Exception as error:
        result = {"type": "error", "code": failure_code(error).value}
    proxy.output.write(json.dumps(result) + "\n")
    proxy.output.flush()


if __name__ == "__main__":
    asyncio.run(main())
