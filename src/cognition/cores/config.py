"""Monitor configuration for the learning and vision cores. Not a plant command."""

from cognition.control.gateway import Rejected
from cognition.domain import CoreConfig, MonitorConfigAction
from cognition.persistence.store import Store

ACTIVE_ALERT_SCORE = 0.25
MAX_MASK_TICKS = 600


class CoreConfigDesk:
    def __init__(self, store: Store) -> None:
        self.store = store

    def get(self, plant_id: str, core: str) -> CoreConfig:
        try:
            return CoreConfig.model_validate_json(
                self.store.get("core_config", f"{plant_id}:{core}")
            )
        except KeyError:
            return CoreConfig(plant_id=plant_id, core=core)  # type: ignore[arg-type]

    def masked(self, plant_id: str, core: str) -> set[str]:
        tick = self.store.plant(plant_id).tick
        return {c for c, until in self.get(plant_id, core).masked.items() if until > tick}

    def validate(self, platform, plant_id: str, action: MonitorConfigAction) -> None:
        """Rules: never mask a channel with an active alert; limited mask time; bounded gain."""
        if action.setting == "set_sensitivity":
            if action.value is None or not 0.5 <= action.value <= 1.5:
                raise Rejected("Sensitivity must be between 0.5 and 1.5")
            return
        if action.core != "learning":
            raise Rejected("Only the learning core has channels to mask")
        state = platform.store.plant(plant_id)
        if action.target not in {c.id for c in platform.signals.definitions(state)}:
            raise Rejected(f"Unknown channel '{action.target}'")
        if action.setting == "unmask_channel":
            return
        if action.duration_ticks is None or action.duration_ticks > MAX_MASK_TICKS:
            raise Rejected(f"Masking needs a duration of at most {MAX_MASK_TICKS} ticks")
        from cognition.cores.learning.monitor import channel_scores

        for item in channel_scores(platform, plant_id, respect_config=False):
            if item["channel"] == action.target and item["score"] >= ACTIVE_ALERT_SCORE:
                raise Rejected(
                    f"Channel '{action.target}' has an active alert and cannot be masked"
                )

    def apply(self, platform, plant_id: str, action: MonitorConfigAction) -> CoreConfig:
        self.validate(platform, plant_id, action)
        config = self.get(plant_id, action.core)
        tick = self.store.plant(plant_id).tick
        if action.setting == "mask_channel":
            assert action.duration_ticks is not None
            config.masked[action.target] = tick + action.duration_ticks
        elif action.setting == "unmask_channel":
            config.masked.pop(action.target, None)
        else:
            assert action.value is not None
            config.sensitivity = action.value
        self.store.put("core_config", f"{plant_id}:{action.core}", config)
        self.store.audit(
            f"cores:{plant_id}",
            "core_config_changed",
            {"core": action.core, "setting": action.setting, "target": action.target},
        )
        return config
