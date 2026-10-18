"""Route group; stateful work belongs to platform services."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastapi import APIRouter

from cognition.api.context import ApiContext
from cognition.config import worker_interpreter
from cognition.harnesses.base import ModelSettings


def build(context: ApiContext) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/health")
    def health():
        return {"application": "fabrix", "status": "ok", "mode": "simulation", "version": "0.1.0"}

    @router.get("/api/harnesses")
    def harnesses():
        try:
            ModelSettings.from_env().validate()
            credentials = True
        except ValueError:
            credentials = False
        result = []
        for name, package in [
            ("reference", None),
            ("deepagents", "deepagents"),
            ("adk", "google-adk"),
            ("antigravity", "google-antigravity"),
        ]:
            interpreter = worker_interpreter(name)
            try:
                installed = name == "reference" or bool(package and version(package))
            except PackageNotFoundError:
                installed = False
            configured = bool(interpreter and Path(interpreter).is_file()) or installed
            result.append(
                {
                    "name": name,
                    "live_model": name != "reference",
                    "configured": configured,
                    "installed": installed,
                    "credentials": name == "reference" or credentials,
                    "isolated": bool(interpreter),
                    "resume": False,
                }
            )
        return result

    return router
