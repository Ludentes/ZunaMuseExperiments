import numpy as np
from backend.pipeline.types import PipelineFrame, Event, Cadence, BANDS


def test_pipeline_frame_set_get():
    from dataclasses import dataclass

    @dataclass
    class FakeResult:
        value: int

    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    assert frame.get(FakeResult) is None
    assert not frame.has(FakeResult)

    frame.set(FakeResult(value=42))
    result = frame.get(FakeResult)
    assert result is not None
    assert result.value == 42
    assert frame.has(FakeResult)


def test_pipeline_frame_all_results():
    from dataclasses import dataclass

    @dataclass
    class A:
        x: int

    @dataclass
    class B:
        y: str

    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(A(x=1))
    frame.set(B(y="hello"))
    results = frame.all_results()
    assert "A" in results
    assert "B" in results


def test_pipeline_frame_events():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    assert frame.events == []
    frame.events.append(Event(kind="blink", timestamp=1.0, confidence=0.9))
    assert len(frame.events) == 1


def test_cadence_values():
    assert Cadence.FAST.value == "fast"
    assert Cadence.SLOW.value == "slow"


def test_bands_muse2():
    assert BANDS["alpha"] == (7.5, 13.0)
    assert BANDS["gamma"] == (30.0, 44.0)
    assert len(BANDS) == 5
