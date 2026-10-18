"""Route group; stateful work belongs to platform services."""

import os
from contextlib import asynccontextmanager
from importlib.resources import files

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cognition.api.context import ApiContext
from cognition.api.routes import (
    agents,
    automation,
    business,
    capabilities,
    cores,
    incidents,
    insights,
    operations,
    orders,
    plants,
    sensing,
    system,
    world,
)
from cognition.config import load_environment
from cognition.domain import Industry, PlantSpec
from cognition.persistence.store import Store
from cognition.runtime.automation import Automation
from cognition.runtime.platform import Platform


def create_app(path: str | None = None) -> FastAPI:
    load_environment()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(path or os.getenv("COGNITION_DB") or "data/platform.db")
        app.state.platform = Platform(store, float(os.getenv("COGNITION_TIMEOUT", "120")))
        if not store.plants():
            for industry in Industry:
                app.state.platform.onboard(
                    PlantSpec(
                        id=f"{industry}-demo", name=f"{industry.title()} plant", industry=industry
                    )
                )
        app.state.platform.reconcile()
        for state in store.plants():
            app.state.platform.registry.ensure(state)
        app.state.automation = Automation(app.state.platform)
        app.state.automation.start()
        if os.getenv("COGNITION_WORLD_AUTOSTART", "").lower() in ("1", "true", "yes"):
            for state in store.plants():
                app.state.platform.world.start(state.spec.id)
        try:
            yield
        finally:
            await app.state.automation.close()
            await app.state.platform.world.close()
            await app.state.platform.core_agents.close()
            store.close()

    app = FastAPI(title="Avenor", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def revalidate_workspace_assets(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        elif response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        return response

    context = ApiContext(app)
    for module in (
        system,
        plants,
        capabilities,
        automation,
        incidents,
        operations,
        world,
        business,
        sensing,
        cores,
        orders,
        insights,
        agents,
    ):
        app.include_router(module.build(context))

    web = str(files("cognition").joinpath("web"))
    app.mount("/static", StaticFiles(directory=web), name="static")

    @app.get("/fleet", include_in_schema=False)
    @app.get("/studio", include_in_schema=False)
    @app.get("/faculties", include_in_schema=False)
    @app.get("/agents", include_in_schema=False)
    @app.get("/investigations", include_in_schema=False)
    @app.get("/impact", include_in_schema=False)
    @app.get("/assets", include_in_schema=False)
    @app.get("/system", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(f"{web}/index.html")

    return app
