# Pipeline Architecture

**Last updated:** 2026-03-09

The signal processing pipeline replaces the monolithic `build_metrics()` function with a chain of pluggable stages. Each stage reads inputs from a shared `PipelineFrame`, computes results, and stores them as typed dataclass objects. Stages are swappable — change one line in `factory.py` to substitute BrainFlow's bandpass filter with wavelet denoising, or swap the built-in MLModel classifier with a custom ONNX model.

---

## Data Flow

```
BrainFlow Acquisition
        │
        ├─── FAST tick (~16ms) ──→ [BlinkDetector] → [ClenchDetector] → Actions
        │                                                                  │
        │                                                          ┌───────┴───────┐
        │                                                     LogAction    MQTTAction
        │
        └─── SLOW tick (~2s) ───→ [BandPassFilter] → [BandPowerExtractor]
                                         │             → [SignalQualityChecker]
                                         │             → [HeartRateExtractor]
                                         │             → [HeadMotionExtractor]
                                         │
                                         └──→ frame_to_metrics() → WebSocket → Dashboard
```

## Core Types

### `PipelineFrame`

The frame carries raw sensor data and collects typed results from stages.

```python
@dataclass
class PipelineFrame:
    # Fixed inputs (hardware-determined)
    eeg: np.ndarray | None    # (4, N) µV at 256Hz — TP9, AF7, AF8, TP10
    ppg: np.ndarray | None    # (3, M) raw at 64Hz — Red, IR, Ambient
    imu: np.ndarray | None    # (6, K) g's/dps at 52Hz — accel[3] + gyro[3]
    timestamp: float

    # Open result registry
    _results: dict[str, Any]

    # Detected events (append-only by detector stages)
    events: list[Event]

    def set(self, result: Any) -> None       # store by class name
    def get(self, cls: type[T]) -> T | None  # retrieve typed, or None
    def has(self, cls: type) -> bool          # check presence
    def all_results(self) -> dict[str, Any]  # for serializer
```

**Rules:**
- Stages MUST NOT write to `eeg`, `ppg`, `imu`, or `timestamp`. These are owned by the pipeline runner.
- Stages write results via `frame.set()`. Stages read other stages' results via `frame.get()`.
- Detector stages append to `frame.events`. Feature stages do not touch `events`.

### `Event`

```python
@dataclass
class Event:
    kind: str           # "single_blink", "double_blink", "triple_blink", "clench"
    timestamp: float    # time.time()
    confidence: float   # 0.0 - 1.0
    channel: str | None # source channel, e.g. "AF7"
    metadata: dict      # stage-specific extra data
```

### `Cadence`

```python
class Cadence(Enum):
    FAST = "fast"   # every poll cycle (~16ms) — event detection
    SLOW = "slow"   # every metrics cycle (~2s) — spectral features, vitals
```

### `BANDS` (Muse 2 / Muse SDK ranges)

```python
BANDS = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (7.5, 13.0),
    "beta":  (13.0, 30.0),
    "gamma": (30.0, 44.0),
}
```

---

## Stage Base Class

```python
class Stage(ABC):
    name: str
    cadence: Cadence

    @abstractmethod
    def process(self, frame: PipelineFrame) -> None: ...
```

**Contract for all stages:**
- `process()` reads from frame (inputs and/or other stages' results via `frame.get()`).
- `process()` writes its result via `frame.set(MyResultDataclass(...))`.
- If the stage's required input is `None` or insufficient, it MUST return silently (no result set).
- State across frames (rolling windows, accumulators) is kept as instance attributes.
- Stages MUST NOT call `frame.set()` with another stage's result type.

---

## Stage Contracts

### `BandPassFilter`

**Purpose:** Remove noise from raw EEG. Powerline notch + bandpass.

| | |
|---|---|
| **Cadence** | SLOW |
| **Reads** | `frame.eeg` |
| **Writes** | `PreprocessingResult` |
| **BrainFlow API** | `remove_environmental_noise`, `perform_bandpass` |
| **Swappable with** | `WaveletDenoiser`, `ICAFilter`, `ZunaPreprocessor` |

```python
@dataclass
class PreprocessingResult:
    eeg_filtered: np.ndarray   # same shape as input eeg
```

**Config:**
- `lowcut: float = 1.0` — highpass cutoff Hz
- `highcut: float = 45.0` — lowpass cutoff Hz
- `notch: float = 50.0` — powerline frequency (0 to disable)
- `order: int = 4` — filter order
- `filter_type: int = 0` — BrainFlow FilterTypes (0=Butterworth)

**Behavior:**
1. Copy `frame.eeg` (BrainFlow filters in-place)
2. For each channel: `remove_environmental_noise` if notch > 0, then `perform_bandpass`
3. `frame.set(PreprocessingResult(eeg_filtered=...))`
4. If `frame.eeg` is None or has < `order * 3` samples, return without setting result.

---

### `WaveletDenoiser`

**Purpose:** Alternative preprocessor using wavelet denoising.

| | |
|---|---|
| **Cadence** | SLOW |
| **Reads** | `frame.eeg` |
| **Writes** | `PreprocessingResult` |
| **BrainFlow API** | `perform_wavelet_denoising` |
| **Swappable with** | `BandPassFilter` |

**Config:**
- `wavelet: str = "db4"`
- `decomp_level: int = 4`

**Behavior:**
1. Copy `frame.eeg`
2. For each channel: `perform_wavelet_denoising`
3. `frame.set(PreprocessingResult(eeg_filtered=...))`

---

### `BandPowerExtractor`

**Purpose:** Compute frequency band powers, theta/beta ratio, frontal alpha asymmetry.

| | |
|---|---|
| **Cadence** | SLOW |
| **Reads** | `PreprocessingResult` (falls back to `frame.eeg` if no preprocessor ran) |
| **Writes** | `BandPowerResult` |
| **BrainFlow API** | `detrend`, `get_psd_welch`, `get_band_power` |
| **Swappable with** | `WaveletFeatureExtractor` (future — wavelet decomposition instead of FFT) |

```python
@dataclass
class BandPowerResult:
    band_powers: dict[str, list[float]]   # {band_name: [per_channel_power_uV2]}
    theta_beta_ratio: list[float]         # per channel
    frontal_alpha_asymmetry: float        # log(AF8_alpha) - log(AF7_alpha)
```

**Config:**
- `bands: dict[str, tuple[float, float]] = BANDS` — frequency band definitions
- `smoothing: bool = False` — apply `perform_rolling_filter` to band power history
- `smoothing_window: int = 3` — rolling average window size (in ticks)

**Behavior:**
1. Get EEG: `prep = frame.get(PreprocessingResult)` → use `prep.eeg_filtered` if available, else `frame.eeg`
2. For each channel: `detrend` → `get_psd_welch` → `get_band_power` per band
3. Compute theta/beta ratio per channel
4. Compute FAA from alpha powers on AF7 (idx 1) and AF8 (idx 2)
5. `frame.set(BandPowerResult(...))`
6. Requires at least `nfft` samples (256 for 256Hz). Return without result if insufficient.

---

### `SignalQualityChecker`

**Purpose:** Per-channel signal quality score and overall fit status.

| | |
|---|---|
| **Cadence** | SLOW |
| **Reads** | `frame.eeg` |
| **Writes** | `SignalQualityResult` |
| **BrainFlow API** | `get_railed_percentage` (can use), `calc_stddev` (can use) |
| **Swappable with** | Custom quality scorer |

```python
@dataclass
class SignalQualityResult:
    quality: dict[str, float]   # {channel_name: 0.0-1.0}
    fit_status: str             # "good" | "adjust" | "poor"
```

**Behavior:**
1. For each channel: compute railed percentage (samples > 995µV) and standard deviation
2. Score: `min(railed_score, std_score)` where railed_score penalizes >10% railed, std_score penalizes <2µV (flatline) or >200µV (excessive noise)
3. Fit status: 0 poor channels → "good", 1-2 → "adjust", 3+ → "poor"
4. `frame.set(SignalQualityResult(...))`

---

### `HeartRateExtractor`

**Purpose:** Heart rate, SpO2, and HRV from PPG sensor.

| | |
|---|---|
| **Cadence** | SLOW |
| **Reads** | `frame.ppg` |
| **Writes** | `HeartRateResult` |
| **BrainFlow API** | `get_heart_rate`, `get_oxygen_level` |
| **Swappable with** | Custom PPG peak detector |

```python
@dataclass
class HeartRateResult:
    heart_rate_bpm: float
    spo2_percent: float
    hrv_rmssd_ms: float
```

**Internal state:**
- `_ppg_accumulator: np.ndarray | None` — rolling PPG buffer, persists across ticks. PPG arrives at ~128 samples/tick (64Hz × 2s) but `get_heart_rate` needs ≥1024 samples.
- Max accumulator size: 1280 samples (20s at 64Hz).

**Behavior:**
1. Append `frame.ppg` to `_ppg_accumulator`, trim to max size
2. If accumulator < 1024 samples, return without result
3. Call `get_heart_rate(ir, red, 64, 1024)` — fft_size MUST be ≤ data length AND ≥ 1024
4. Call `get_oxygen_level(ir, red, 64)`
5. Compute HRV RMSSD from peak detection on bandpass-filtered (0.5-4Hz) IR signal
6. `frame.set(HeartRateResult(...))`

---

### `HeadMotionExtractor`

**Purpose:** Head movement, pose, and motion artifact flag from IMU.

| | |
|---|---|
| **Cadence** | SLOW |
| **Reads** | `frame.imu` |
| **Writes** | `HeadMotionResult` |
| **BrainFlow API** | — (pure numpy) |
| **Swappable with** | Custom IMU processor |

```python
@dataclass
class HeadMotionResult:
    head_movement: float              # RMS of per-axis std-dev (0 = still)
    head_pose: tuple[float, float]    # (pitch, roll) in degrees
    motion_artifact: bool             # True if movement > 0.05
```

**Behavior:**
1. Split IMU: `accel = imu[:3]`, `gyro = imu[3:]` (gyro unused for now)
2. Movement: RMS of per-axis standard deviation over the window
3. Pose: `atan2` pitch and roll from mean accelerometer vector
4. Artifact: `movement > 0.05`
5. `frame.set(HeadMotionResult(...))`
6. Requires ≥2 samples. Return without result if insufficient.

---

### `BlinkDetector`

**Purpose:** Detect single, double, and triple blinks from frontal EEG.

| | |
|---|---|
| **Cadence** | FAST |
| **Reads** | `frame.eeg` |
| **Writes** | `frame.events` (append) |
| **BrainFlow API** | `detect_peaks_z_score` |
| **Swappable with** | Custom threshold detector |

**No result dataclass** — blink detectors produce `Event` objects only.

**Internal state:**
- Rolling window of recent EEG on AF7 (idx 1) and AF8 (idx 2)
- Refractory timer: ignore peaks within 300ms of last detected blink
- Pattern buffer: timestamps of recent blinks for double/triple classification

**Config:**
- `z_threshold: float = 3.5` — z-score threshold for peak detection
- `refractory_ms: float = 300` — minimum gap between distinct blinks
- `double_window_ms: float = 600` — max gap to count as double blink
- `triple_window_ms: float = 900` — max gap to count as triple blink

**Behavior:**
1. Append `frame.eeg` channels AF7/AF8 to rolling window
2. Run `detect_peaks_z_score` on the window
3. For each detected peak: check refractory period, record timestamp
4. After refractory period expires, classify pattern:
   - 1 peak → `Event("single_blink", confidence=0.9)`
   - 2 peaks within `double_window_ms` → `Event("double_blink", confidence=0.85)`
   - 3 peaks within `triple_window_ms` → `Event("triple_blink", confidence=0.8)`
5. Append classified events to `frame.events`

---

### `ClenchDetector`

**Purpose:** Detect jaw clench from temporal EEG (EMG artifact on TP9/TP10).

| | |
|---|---|
| **Cadence** | FAST |
| **Reads** | `frame.eeg` |
| **Writes** | `frame.events` (append), `ClenchResult` |
| **BrainFlow API** | `perform_bandpass` (>20Hz highpass for EMG band) |
| **Swappable with** | Custom EMG envelope detector |

```python
@dataclass
class ClenchResult:
    jaw_clench: bool
```

**Internal state:**
- Rolling window of recent EEG on TP9 (idx 0) and TP10 (idx 3)
- Debounce timer: clench must sustain >100ms to count

**Config:**
- `emg_lowcut: float = 20.0` — highpass for EMG band
- `emg_highcut: float = 45.0` — lowpass
- `threshold_uv: float = 50.0` — envelope threshold
- `min_duration_ms: float = 100` — minimum clench duration

**Behavior:**
1. Append TP9/TP10 to rolling window
2. Bandpass 20-45Hz to isolate EMG
3. Compute envelope (absolute value, smoothed)
4. If envelope > threshold for > min_duration: set `jaw_clench = True`, append `Event("clench")`
5. `frame.set(ClenchResult(jaw_clench=...))` + append to `frame.events`

---

## Future Stage Contracts (not implemented yet)

### `ConcentrationScorer`

| | |
|---|---|
| **Cadence** | SLOW |
| **Reads** | `BandPowerResult` |
| **Writes** | `ConcentrationResult` |
| **BrainFlow API** | `MLModel(MINDFULNESS)`, `MLModel(RESTFULNESS)` |

```python
@dataclass
class ConcentrationResult:
    concentration_score: float   # 0.0 - 1.0
    relaxation_score: float      # 0.0 - 1.0
```

### `AlphaBlockingDetector`

| | |
|---|---|
| **Cadence** | SLOW |
| **Reads** | `BandPowerResult` |
| **Writes** | `AlphaBlockingResult`, `frame.events` |
| **Requires** | Calibration baseline (personal alpha power with eyes closed) |

```python
@dataclass
class AlphaBlockingResult:
    alpha_blocked: bool
    alpha_ratio: float   # current / baseline (< 0.5 = blocked)
```

---

## Actions

### `LogAction`

Logs every event at INFO level. Always included in pipeline.

```
INFO bci.events: single_blink confidence=0.92 channel=AF7
```

### `WebSocketBroadcastAction`

Serializes events as JSON and broadcasts to connected dashboard clients.

```json
{"type": "bci_event", "kind": "single_blink", "confidence": 0.92, "channel": "AF7"}
```

### `MQTTAction`

Publishes events to MQTT broker. Maps event kind → topic.

| Event | MQTT Topic | Payload |
|-------|-----------|---------|
| `single_blink` | `bci/command/blink` | `{"count": 1}` |
| `double_blink` | `bci/command/blink` | `{"count": 2}` |
| `triple_blink` | `bci/command/blink` | `{"count": 3}` |
| `clench` | `bci/command/clench` | `{"duration_ms": 150}` |

**Config:** `broker_host`, `broker_port`, `topic_prefix`

---

## Serializer: `frame_to_metrics()`

Single translation layer between pipeline results and the WebSocket JSON protocol the frontend expects. When adding a stage whose output should appear on the dashboard, add one `if` block here.

```python
def frame_to_metrics(frame: PipelineFrame) -> dict:
    metrics = {}
    bp = frame.get(BandPowerResult)
    if bp:
        metrics["eeg"] = { "band_powers": bp.band_powers, ... }
    sq = frame.get(SignalQualityResult)
    if sq:
        metrics.setdefault("eeg", {}).update({ "signal_quality": sq.quality, ... })
    hr = frame.get(HeartRateResult)
    if hr:
        metrics["ppg"] = { "heart_rate_bpm": hr.heart_rate_bpm, ... }
    hm = frame.get(HeadMotionResult)
    if hm:
        metrics["imu"] = { "head_movement": hm.head_movement, ... }
    cl = frame.get(ClenchResult)
    if cl:
        metrics.setdefault("imu", {})["jaw_clench"] = cl.jaw_clench
    return metrics
```

---

## Pipeline Assembly

```python
# backend/pipeline/factory.py

def create_default_pipeline() -> Pipeline:
    stages = [
        # SLOW
        BandPassFilter(lowcut=1.0, highcut=45.0, notch=50.0),
        BandPowerExtractor(),
        SignalQualityChecker(),
        HeartRateExtractor(),
        HeadMotionExtractor(),
        # FAST
        BlinkDetector(),
        ClenchDetector(),
    ]
    actions = [
        LogAction(),
        WebSocketBroadcastAction(),
        # MQTTAction(broker="localhost", port=1883),
    ]
    return Pipeline(stages, actions)
```

To swap: change one line. To add: append one line + write the stage file.

---

## File Layout

```
backend/pipeline/
├── __init__.py          # Pipeline class
├── types.py             # PipelineFrame, Event, Cadence, BANDS
├── base.py              # Stage, Action ABCs
├── factory.py           # create_default_pipeline()
├── serialize.py         # frame_to_metrics()
├── stages/
│   ├── __init__.py
│   ├── preprocessing.py # BandPassFilter, WaveletDenoiser, PreprocessingResult
│   ├── features.py      # BandPowerExtractor, SignalQualityChecker,
│   │                    #   HeartRateExtractor, HeadMotionExtractor + results
│   └── detectors.py     # BlinkDetector, ClenchDetector, ClenchResult
└── actions/
    ├── __init__.py
    ├── log.py           # LogAction
    ├── websocket.py     # WebSocketBroadcastAction
    └── mqtt.py          # MQTTAction (stub until needed)
```
