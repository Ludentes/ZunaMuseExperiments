from __future__ import annotations

import logging

from backend.pipeline.base import Action
from backend.pipeline.types import Event

log = logging.getLogger("bci.events")


class LogAction(Action):
    def handle(self, events: list[Event]) -> None:
        for event in events:
            log.info(
                "%s confidence=%.2f channel=%s",
                event.kind, event.confidence, event.channel,
            )
