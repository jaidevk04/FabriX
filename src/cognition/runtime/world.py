"""WorldClock: ticks plants on its own, independent of agent automation modes."""

import asyncio
import time

from cognition.config import kill_after_seconds
from cognition.domain import State, WorldStatus

MIN_INTERVAL, MAX_INTERVAL = 0.2, 60.0


class WorldEffects:
    """Runs the world hooks in order inside one connector transaction."""

    def __init__(self, *parts) -> None:
        self.parts = parts

    def apply(self, db, state: State) -> State:
        for part in self.parts:
            state = part.apply(db, state)
        return state

    def offset(self, plant_id: str) -> float:
        return sum(part.offset(plant_id) for part in self.parts)

    def reset(self, db, plant_id: str) -> None:
        for part in self.parts:
            part.reset(db, plant_id)


class WorldClock:
    """Per-plant tick loops. Never auto-started unless the host sets COGNITION_WORLD_AUTOSTART."""

    def __init__(self, platform) -> None:
        self.platform = platform
        self.tasks: dict[str, asyncio.Task] = {}
        self.intervals: dict[str, float] = {}
        # Kill switch: wall-clock watchdog per running plant, and the plants where it has tripped.
        self.watchdogs: dict[str, asyncio.Task] = {}
        self.started: dict[str, tuple[float, float]] = {}
        self.tripped: dict[str, dict] = {}
        # Live mode keeps sampling during investigations; strict mode freezes the plant.
        self.pause_when_busy = bool(getattr(platform, "strict", False))

    def running(self, plant_id: str) -> bool:
        task = self.tasks.get(plant_id)
        return task is not None and not task.done()

    def start(self, plant_id: str, interval_seconds: float = 1.0) -> WorldStatus:
        self.platform.store.plant(plant_id)
        if not MIN_INTERVAL <= interval_seconds <= MAX_INTERVAL:
            raise ValueError(f"Interval must be between {MIN_INTERVAL} and {MAX_INTERVAL} seconds")
        if self.running(plant_id):
            raise ValueError("World clock is already running for this plant")
        self.intervals[plant_id] = interval_seconds
        self.platform.signals.clear(plant_id)
        self.tripped.pop(plant_id, None)
        self.tasks[plant_id] = asyncio.create_task(self._loop(plant_id, interval_seconds))
        limit = kill_after_seconds()
        if limit > 0:
            self.started[plant_id] = (time.monotonic(), limit)
            self.watchdogs[plant_id] = asyncio.create_task(self._watchdog(plant_id, limit))
        self.platform.store.audit(
            f"world:{plant_id}", "world_started", {"interval_seconds": interval_seconds}
        )
        return self.status(plant_id)

    async def stop(self, plant_id: str) -> WorldStatus:
        watchdog = self.watchdogs.pop(plant_id, None)
        self.started.pop(plant_id, None)
        if watchdog is not None and watchdog is not asyncio.current_task():
            watchdog.cancel()
        task = self.tasks.pop(plant_id, None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.platform.store.audit(f"world:{plant_id}", "world_stopped", {})
        return self.status(plant_id)

    async def close(self) -> None:
        for plant_id in list(self.tasks):
            await self.stop(plant_id)

    def tick_once(self, plant_id: str) -> State:
        return self.platform.sample(plant_id)

    async def _watchdog(self, plant_id: str, limit: float) -> None:
        await asyncio.sleep(limit)
        await self.platform.kill(plant_id, limit)

    def kill_state(self, plant_id: str) -> dict:
        """The kill switch as the UI shows it: the limit, time left and whether it tripped."""
        started = self.started.get(plant_id)
        limit = started[1] if started else kill_after_seconds()
        left = None
        if started and self.running(plant_id):
            left = max(0.0, started[1] - (time.monotonic() - started[0]))
        trip = self.tripped.get(plant_id)
        return {
            "configured": limit > 0,
            "after_seconds": limit,
            "seconds_left": left,
            "tripped": trip is not None,
            "tripped_at": trip["at"] if trip else None,
        }

    def status(self, plant_id: str) -> WorldStatus:
        state = self.platform.store.plant(plant_id)
        active = self.platform.faults.events(plant_id, include_cleared=False)
        kill = self.kill_state(plant_id)
        return WorldStatus(
            plant_id=plant_id,
            running=self.running(plant_id),
            interval_seconds=self.intervals.get(plant_id, 1.0),
            tick=state.tick,
            sim_seconds=state.sim_seconds,
            active_events=len(active),
            kill_after_seconds=kill["after_seconds"],
            kill_seconds_left=kill["seconds_left"],
            kill_tripped=kill["tripped"],
        )

    async def _loop(self, plant_id: str, interval: float) -> None:
        due = time.monotonic()
        while True:
            if not (self.pause_when_busy and plant_id in self.platform.busy):
                try:
                    self.tick_once(plant_id)
                except KeyError:
                    return
            due += interval
            await asyncio.sleep(max(0.0, due - time.monotonic()))
