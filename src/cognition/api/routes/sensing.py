"""Sensing routes: signals, cameras and fleet. Unauthenticated, loopback only."""

from fastapi import APIRouter, HTTPException, Response

from cognition.api.context import ApiContext


def build(context: ApiContext) -> APIRouter:
    router = APIRouter(tags=["sensing"])
    platform, require = context.platform, context.require

    @router.get("/api/plants/{plant_id}/signals")
    def signals(plant_id: str):
        require(plant_id)
        return platform().signals.read_all(plant_id)

    @router.get("/api/plants/{plant_id}/signals/history")
    def history(plant_id: str):
        """Recent samples recorded while the world ran, for the Learning view to replay."""
        require(plant_id)
        return platform().signals.history(plant_id)

    @router.get("/api/plants/{plant_id}/signals/{channel}/window")
    def window(plant_id: str, channel: str, n: int = 256):
        require(plant_id)
        try:
            samples, rate = platform().signals.window(plant_id, channel, n)
            features = platform().signals.features(plant_id, channel, n)
        except KeyError as exc:
            raise HTTPException(404, "Channel not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"channel": channel, "rate_hz": rate, "samples": samples, "features": features}

    @router.get("/api/plants/{plant_id}/cameras")
    def cameras(plant_id: str):
        require(plant_id)
        return platform().cameras.summary(plant_id)

    @router.get("/api/plants/{plant_id}/cameras/clips")
    def clips(plant_id: str):
        """Footage plan: expected clip files per camera state and which are present."""
        require(plant_id)
        return platform().cameras.clip_plan(plant_id)

    @router.get("/api/plants/{plant_id}/cameras/{camera}/frame.svg")
    def frame(plant_id: str, camera: str, overlay: bool = True):
        require(plant_id)
        try:
            svg = platform().cameras.frame_svg(plant_id, camera, boxes=overlay)
        except KeyError as exc:
            raise HTTPException(404, "Camera not found") from exc
        return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})

    @router.get("/api/plants/{plant_id}/fleet")
    def fleet(plant_id: str):
        require(plant_id)
        return platform().fleet.state(plant_id)

    return router
