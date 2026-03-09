from dataclasses import dataclass
from backend.pipeline.types import PipelineFrame, Cadence, Event
from backend.pipeline.base import Stage, Action, Pipeline


class IncrementStage(Stage):
    name = "increment"
    cadence = Cadence.SLOW

    def process(self, frame: PipelineFrame) -> None:
        @dataclass
        class IncrResult:
            count: int

        prev = frame.get(IncrResult)
        frame.set(IncrResult(count=(prev.count + 1) if prev else 1))


class CollectAction(Action):
    def __init__(self):
        self.collected: list[Event] = []

    def handle(self, events: list[Event]) -> None:
        self.collected.extend(events)


def test_pipeline_runs_slow_stages():
    stage = IncrementStage()
    pipeline = Pipeline(stages=[stage], actions=[])
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    pipeline.run(Cadence.SLOW, frame)
    assert len(frame.all_results()) == 1


def test_pipeline_skips_wrong_cadence():
    stage = IncrementStage()  # SLOW
    pipeline = Pipeline(stages=[stage], actions=[])
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    pipeline.run(Cadence.FAST, frame)
    assert len(frame.all_results()) == 0


def test_pipeline_dispatches_events_to_actions():
    action = CollectAction()
    pipeline = Pipeline(stages=[], actions=[action])
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.events.append(Event(kind="test", timestamp=1.0, confidence=1.0))
    pipeline.run(Cadence.FAST, frame)
    assert len(action.collected) == 1
    assert action.collected[0].kind == "test"
