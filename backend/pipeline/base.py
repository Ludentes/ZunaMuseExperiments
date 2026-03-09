from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from backend.pipeline.types import Cadence, Event, PipelineFrame

log = logging.getLogger("pipeline")


class Stage(ABC):
    name: str
    cadence: Cadence

    @abstractmethod
    def process(self, frame: PipelineFrame) -> None: ...


class Action(ABC):
    @abstractmethod
    def handle(self, events: list[Event]) -> None: ...


class Pipeline:
    def __init__(self, stages: list[Stage], actions: list[Action]):
        self.stages = stages
        self.actions = actions

    def run(self, cadence: Cadence, frame: PipelineFrame) -> None:
        for stage in self.stages:
            if stage.cadence != cadence:
                continue
            try:
                stage.process(frame)
            except Exception:
                log.exception("Stage %s failed", stage.name)

        if frame.events:
            for action in self.actions:
                try:
                    action.handle(frame.events)
                except Exception:
                    log.exception("Action %s failed", type(action).__name__)
