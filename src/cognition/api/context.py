"""Application-scoped services; no global store or worker singleton."""

from dataclasses import dataclass

from fastapi import FastAPI, HTTPException

from cognition.runtime.platform import Platform


@dataclass(frozen=True)
class ApiContext:
    app: FastAPI

    def platform(self) -> Platform:
        return self.app.state.platform

    def require(self, plant_id: str) -> None:
        try:
            self.platform().store.plant(plant_id)
        except KeyError as error:
            raise HTTPException(404, "Plant not found") from error

    def require_manual(self, plant_id: str) -> None:
        self.require(plant_id)
        if plant_id in self.platform().busy or self.app.state.automation.state(plant_id).enabled:
            raise HTTPException(
                409, "Stop automation or the current investigation before a manual investigation"
            )
