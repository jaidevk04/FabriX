"""Public ASGI entry point; keep launchers and tests compatible."""

from cognition.api.app import create_app

app = create_app()

__all__ = ["app", "create_app"]
