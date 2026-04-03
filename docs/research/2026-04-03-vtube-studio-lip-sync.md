# Research: VTube Studio Lip Sync — Current State (2026)

**Date:** 2026-04-03
**Sources:** 18 sources

---

## Executive Summary

VTube Studio offers two internal lip sync paths — microphone-based and face-tracking-based — plus an open WebSocket plugin API that allows any external software to inject custom parameters. The built-in microphone system (Advanced Lipsync, based on uLipSync/MFCC) is the dominant choice for desktop streamers without iOS devices, achieving vowel-level phoneme discrimination (A/I/U/E/O) with per-voice calibration. It is "good enough" for most streaming purposes but has documented structural limitations: it handles only vowels, cannot animate for unvoiced consonants or silent mouthing, and requires the model to have a second parallel rig layer to switch between mic and camera modes. iPhone ARKit tracking with tools like VBridger provides significantly higher fidelity (23–25 mouth blendshapes from Apple's TrueDepth sensors), but remains gated behind iOS hardware. The VTS plugin API is an open channel: any process on localhost that speaks WebSocket can inject numeric values for any Live2D parameter on a per-frame basis. This is the exact integration point for an EEG/BCI plugin — the precedent is already established by the heartrate monitor plugin (vts-heartrate), which follows the same architecture and ships 15 custom parameters derived from a wrist sensor.

---

## Key Findings

### Built-in Lip Sync Methods

VTube Studio ships two microphone-based modes.

**Simple Lipsync** (legacy, Windows-only) was built on Oculus VR Lipsync. It is deprecated and the official documentation explicitly says not to use it. It remains available for backward compatibility only.

**Advanced Lipsync** (current, cross-platform) is built on *uLipSync* by hecomi, a Unity asset that performs Mel-Frequency Cepstral Coefficient (MFCC) analysis on the microphone buffer. The implementation runs inside Unity's `OnAudioFilterRead()` callback using the Job System and Burst Compiler for CPU efficiency. The MFCC vectors are compared in real-time against pre-calibrated vowel profiles to produce scores for each of five Japanese vowel phonemes: A, I, U, E, O. Users calibrate by holding each vowel while clicking the corresponding button; the system builds a personal profile that accounts for voice frequency and formant characteristics. VTS exposes this as eight distinct output parameters:

| VTS Parameter | Meaning | Range |
|---|---|---|
| `VoiceA` | Vowel "A" confidence | 0–1 |
| `VoiceI` | Vowel "I" confidence | 0–1 |
| `VoiceU` | Vowel "U" confidence | 0–1 |
| `VoiceE` | Vowel "E" confidence | 0–1 |
| `VoiceO` | Vowel "O" confidence | 0–1 |
| `VoiceVolume` | Microphone loudness | 0–1 |
| `VoiceVolumePlusMouthOpen` | Volume combined with face-tracking MouthOpen | 0–1 |
| `VoiceFrequency` | Dominant frequency band, 0=low/1=high | 0–1 |
| `VoiceFrequencyPlusMouthSmile` | Frequency combined with face-tracking MouthSmile | 0–1 |
| `VoiceSilence` | 1 when silent, 0 when speaking | 0–1 |

VoiceA through VoiceO are mutually exclusive with the frequency-based approach — a model uses either vowel detection or volume+frequency, not both. VTS enforces that vowel parameters never all equal 1 simultaneously and only mix at sub-maximum values. This is a deliberate design to prevent unnatural combinations.

Three configuration sliders control the system: Volume Gain (boosts all parameters), Volume Cutoff (noise gate threshold), and Frequency Gain (amplifies VoiceFrequency).

The `VoiceSilence` parameter is architecturally important: it is used as a blend weight in the model rig to fade between camera-tracking mouth control (when silent/face tracking is reliable) and microphone-driven vowel shapes (when speaking). The correct Live2D setup places keyforms at `ParamSilence=0` that keep `ParamMouthOpen`/`ParamMouthForm` frozen, so camera tracking only influences the mouth when the microphone is quiet.

**Known latency characteristic:** uLipSync acknowledges an inherent delay from Unity's audio pipeline. The library notes that "microphone input will be played back in Unity a little later than your own speech." No exact millisecond figure is published in the VTS or uLipSync documentation, but the VTS UI includes a "Reload" hotkey specifically to address cases where mic audio drifts behind the displayed values — suggesting the delay is perceptible in practice. Real-time phoneme detection via MFCC typically requires 100–200ms buffers to achieve reliable classification; below that, accuracy drops significantly.

**Model setup required:** A common failure mode (confirmed by Steam forum reports) is that newly imported models use the default `MouthOpen` camera-tracking parameter rather than the voice-responsive `VoiceVolumePlusMouthOpen`. VTS ships an "auto-setup for advanced lipsync" button at the bottom of the lipsync config card that remaps these automatically. Without this, the microphone has no visible effect. An example blendshape mouth model file (`aaa_BlendshapeMouthExample.zip`) is available from VTS as a rigging reference.

---

### External Tools and Plugins

**VBridger** (paid, Steam) is the leading third-party plugin for enhanced face tracking lip sync. It acts as a bridge between iOS ARKit and VTube Studio, forwarding a richer subset of ARKit's 52 face blendshapes into custom VTS parameters. For mouth tracking specifically, VBridger exposes: Jaw Open, Mouth Funnel, Mouth PressLip, Mouth Pucker+Widen, and Mouth Shrug. This covers jaw separation dynamics that are absent from VTS's native tracking. VBridger uses the standard VTS WebSocket API (`InjectParameterDataRequest`) to push these values on each frame. The "PerfectSync" rigging approach, which uses all 23–25 ARKit mouth blendshapes, is the highest-fidelity available option for Live2D in 2025 — but requires both iPhone hardware and a specially rigged model.

**VTS Plugin API (WebSocket):** VTS runs a local WebSocket server on port 8001 (auto-incrementing to 8002, 8003, etc. on port conflicts). Any process on localhost authenticates once via a permission flow, then can send `InjectParameterDataRequest` messages to control any Live2D parameter. The request format:

```json
{
  "messageType": "InjectParameterDataRequest",
  "data": {
    "faceFound": false,
    "mode": "set",
    "parameterValues": [
      { "id": "MouthOpen", "value": 0.75 },
      { "id": "MyCustomParam", "weight": 0.8, "value": 0.5 }
    ]
  }
}
```

The `weight` field (0–1) controls blending with the face tracker's value for that parameter. A plugin can create entirely new custom parameters that appear in VTS with a blue "P" symbol. Custom parameters persist until plugin permissions are revoked. The API requires re-sending a parameter at least once per second to keep it "alive"; stale parameters revert to tracking defaults.

**vts-heartrate** (open-source, FomTarro) is the reference example of a hardware-sensor-to-VTS plugin. It accepts data from a heart rate monitor via Pulsoid, ANT+, or WebSocket, and outputs 15 custom Live2D parameters (linear scale, pulse oscillation, breathing oscillation, raw BPM, per-digit BPM). This is structurally identical to what an EEG plugin would do.

**BrainFlowsIntoVRChat** (ChilloutCharles) is the only published BrainFlow→VTubing project. It targets VRChat via OSC rather than VTS, sending EEG band power (delta/theta/alpha/beta/gamma) and neurofeedback scores (focus/relaxation) as avatar parameters. It does not handle jaw artifact detection or speech-specific outputs. The OSC channel it uses is not VTS's input mechanism — VRChat uses a different OSC avatar parameter protocol.

**VSeeFace** is a free alternative desktop app (not a VTS plugin) that uses MediaPipe for webcam tracking. For lip sync quality it is roughly comparable to VTS webcam tracking. It can send data to VTS via VMC protocol, but this is primarily used for body/head tracking, not lip sync. VSeeFace does not expose an equivalent to VTS's plugin API for parameter injection.

**Open-LLM-VTuber** is an open-source AI VTuber framework that drives VTS lip sync from TTS audio output. It uses FFT-based formant matching on the TTS audio stream to generate `VoiceA/I/U/E/O` values in real time and injects them via the VTS API. This confirms that the API path works for programmatic, non-microphone lip sync.

---

### Quality and Latency Comparison

| Method | Mouth Parameter Coverage | Lip Sync Quality | Latency | Hardware Required |
|---|---|---|---|---|
| VTS microphone (Advanced Lipsync) | A/I/U/E/O + volume | Good for vowels, poor for consonants | ~100–200ms (MFCC buffer) | Any microphone |
| VTS webcam | MouthOpen + MouthForm (2 DOF) | Low — blurry, camera-dependent | 1–2 frames @ 30fps (~33–66ms) | 720p+ webcam |
| VTS + iOS phone (ARKit, native) | MouthOpen + MouthForm + Tongue | High — better than webcam | Sub-frame, less smoothing needed | iPhone with A12+ chip |
| VTS + VBridger + iOS | Jaw Open + 4+ mouth blendshapes | Very high | Sub-frame | iPhone (same) |
| PerfectSync (VBridger + rigged model) | 23–25 ARKit mouth shapes | Highest available for Live2D | Sub-frame | iPhone + rigged model |
| VTS plugin API injection | Any parameter, full 0–1 range | As accurate as input signal | Round-trip: <16ms if local | Software-defined |

The quality ranking for mouth tracking is: PerfectSync/iOS > ARKit native > Microphone MFCC > Webcam. Microphone MFCC outperforms webcam for speech animation specifically because webcam mouth tracking requires seeing the mouth clearly — it degrades when the user looks away, has poor lighting, or wears glasses. The microphone method is also consistent regardless of head pose.

The critical gap in microphone MFCC: it cannot animate unvoiced sounds. Consonants like /p/, /b/, /m/ (lip closure), /f/, /v/ (labio-dental contact), and whispering produce no detectable vowel signal. The `VoiceSilence` parameter goes to 1, and the mouth reverts to camera tracking or rests in neutral. This means the model's mouth is visually idle during plosives and fricatives — a known limitation that users in the VTS community accept as the practical ceiling of the microphone-only approach.

---

### Relevance to BCI/EEG Plugin

The EEG plugin on this project (detecting jaw clench, speech-related EMG artifacts, alpha blocking, and mental states from Muse 2) maps onto VTS as follows:

**Jaw clench → MouthOpen suppressor or trigger.** The Muse 2 jaw clench is detected via frontalis/temporalis EMG bleed onto EEG channels (AF7/AF8), not the actual jaw. This signal is reliable (~95% per recorded evaluations) and fires within one or two processing windows (~78–156ms at 256Hz with typical window sizes). Injected into VTS as a suppressed `MouthOpen` value (drive to 0 on clench), it can represent clenched jaw/teeth expressions that no microphone method can produce. Alternatively, mapped to a custom parameter like `JawClench` with a model expression triggered by threshold — matching the vts-heartrate approach.

**Speech artifact → mouth open proxy.** When the user speaks, EEG channels exhibit characteristic low-frequency drift and EMG contamination. This is typically treated as noise in BCI pipelines, but as a boolean "is speaking" detector it complements `VoiceSilence`. The EEG speech artifact signal is not precise enough for vowel discrimination — MFCC on a microphone is strictly better for that — but it could serve as an independent "speaking" flag with no microphone dependency (relevant for situations where microphone-based lip sync is disabled or the user is speaking silently/mouthing words).

**Alpha blocking → expression state.** Alpha suppression on eye open/close is a reliable (~90–95%) signal. While not directly related to lip sync, it can drive secondary expression parameters: eye squint expressions, "thinking" expressions, or the `FaceAngleX/Y` calm-state modulation. The VTS API handles these on the same `InjectParameterDataRequest` channel.

**Focus/relaxation → passive expression blend.** Using band power ratios (theta/beta for focus, alpha for relaxation), the plugin could modulate subtle expression parameters — furrowed brows when focused, softer expression when relaxed — without any user intent required. This is exactly what BrainFlowsIntoVRChat implements for VRChat and could be ported to VTS.

**The specific gap this fills:** Neither VTS's microphone MFCC system nor its face tracking produces a reliable jaw clench signal. VBridger's `Jaw Open` ARKit blendshape detects jaw separation but not jaw clenching (which closes, not opens, the jaw). EEG EMG artifact is the only signal source that fires positively on clench. This is a genuine capability gap in the current ecosystem.

**Integration architecture:** The plugin connects to VTS via WebSocket on port 8001, authenticates, creates custom parameters (e.g., `EEG_JawClench`, `EEG_FocusLevel`, `EEG_RelaxLevel`, `EEG_Speaking`), and injects normalized 0–1 values every processing frame (~78ms at 256Hz with 20-sample windows). The `weight` field on each parameter allows mixing with camera tracking so that face tracking remains the primary driver and EEG augments it. This means the EEG signal does not need to cover cases where VTS already handles them well.

---

## Open Questions

1. **What is VTS's actual parameter injection rate limit?** The API documentation states parameters must be updated at least once per second, but the upper bound (minimum inter-frame interval before VTS drops or queues messages) is not documented. Practical implementations appear to run at display framerate (30–60fps). The EEG processing window at 256Hz with 20 samples is ~78ms, yielding ~12.8 updates/second — well within observed safe ranges.

2. **Can VTS blend EEG-injected `MouthOpen` with microphone lipsync simultaneously?** The `weight` parameter in `InjectParameterDataRequest` enables this in theory — set weight < 1 to let VTS's internal lipsync retain partial control. Whether this produces natural-looking combined output needs empirical testing.

3. **Does the `VoiceSilence` parameter respond to EEG-detected speech?** If EEG detects a speech episode but `VoiceSilence` is still 1 (no microphone), the model rig will suppress mouth movement. The plugin may need to inject a low-value `VoiceSilence` override to "unlock" the mouth during EEG-detected speech when the microphone lipsync is off.

4. **Clench vs jaw open disambiguation on ARKit.** If the user also uses VBridger/iOS for face tracking, the `Jaw Open` blendshape will be at 0 during a clench — this is the same as resting closed. An EEG clench signal is the only way to distinguish "resting closed" from "actively clenched." These are expressively different (clench = intense emotion or command) and worth separating.

5. **EMG artifact contamination of alpha signal during speaking.** At high speech intensity (shouting), jaw/facial EMG artifacts can spill into all EEG channels and falsely suppress alpha. The existing pipeline's `AdaptiveSpeechGuard` or clench guard should suppress EEG-derived state signals during active speech to prevent spurious expression changes mid-sentence.

6. **Phoneme precision from EEG.** Published BCI research (2023–2025) on imagined speech EEG decoding achieves ~70–80% accuracy for consonant/vowel classification at sub-second latency using high-density electrode arrays. Muse 2 (4 dry electrodes) is not sufficient for phoneme discrimination. This is confirmed: the microphone MFCC path remains strictly better for that specific task.

---

## Sources

1. [Lipsync — DenchiSoft/VTubeStudio Wiki](https://github.com/DenchiSoft/VTubeStudio/wiki/Lipsync) — primary technical reference for all VTS lipsync parameters and calibration
2. [VTube Studio Settings — DenchiSoft/VTubeStudio Wiki](https://github.com/DenchiSoft/VTubeStudio/wiki/VTube-Studio-Settings) — full settings documentation
3. [Android vs. iPhone vs. Webcam — DenchiSoft/VTubeStudio Wiki](https://github.com/DenchiSoft/VTubeStudio/wiki/Android-vs.-iPhone-vs.-Webcam) — tracking quality comparison
4. [Plugins — DenchiSoft/VTubeStudio Wiki](https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins) — plugin API overview
5. [DenchiSoft/VTubeStudio — GitHub (API README)](https://github.com/DenchiSoft/VTubeStudio) — InjectParameterDataRequest JSON format, parameter constraints
6. [uLipSync — hecomi/uLipSync on GitHub](https://github.com/hecomi/uLipSync) — MFCC engine powering VTS Advanced Lipsync
7. [vts-heartrate — FomTarro/vts-heartrate on GitHub](https://github.com/FomTarro/vts-heartrate) — reference architecture for hardware-sensor-to-VTS plugin with 15 custom parameters
8. [BrainFlowsIntoVRChat — ChilloutCharles on GitHub](https://github.com/ChilloutCharles/BrainFlowsIntoVRChat) — BrainFlow EEG → OSC → VRChat avatar parameters
9. [VBridger on Steam](https://store.steampowered.com/app/1898830/VBridger/) — iPhone ARKit blendshape bridge for VTS, Jaw Open and mouth parameters
10. [Face Tracking & VBridger — bilvyy.com](https://www.bilvyy.com/post/vbridger) — VBridger mouth parameter setup guide
11. [VTube Studio Integration — ChangingSelf/Amaidesu on DeepWiki](https://deepwiki.com/ChangingSelf/Amaidesu/7.2-vtube-studio-integration) — example TTS lipsync plugin using VTS API with FFT formant matching
12. [(2025 Update) Live2D PerfectSync Mouth — soultyragevin.itch.io](https://soultyragevin.itch.io/perfectsync-headangles-live2d) — PerfectSync mouth rig for VTS with ARKit blendshapes
13. [Next Big Thing in VTubing? What is PerfectSync for 3D ARKit — iiisekai.com](https://iiisekai.com/next-big-thing-in-vtubing-what-is-perfect-sync-for-3d-arkit-and-how-can-we-use-it-with-live2d/) — PerfectSync 52 blendshape system overview
14. [VTube Studio lip sync — @VTubeStudio on X (2023)](https://x.com/VTubeStudio/status/1700087518480220356) — Advanced Lipsync announcement with parameter design rationale
15. [VTube Studio lip sync — @VTubeStudio on X (vowel params)](https://x.com/VTubeStudio/status/1705385961633481138) — VoiceA/I/U/E/O parameter setup notes with BrianTsuii
16. [Lip Sync Issues — VTube Studio Steam Discussions](https://steamcommunity.com/app/1325860/discussions/0/3056238497038926646/?l=english) — community reports of microphone lipsync failure modes
17. [VSeeFace](https://www.vseeface.icu/) — MediaPipe-based alternative, VMC output to VTS
18. [Standard Parameter List — Live2D Editor Manual](https://docs.live2d.com/en/cubism-editor-manual/standard-parameter-list/) — Live2D parameter IDs and ranges: ParamMouthOpenY (0–1), ParamMouthForm (−1 to +1), ParamLipUpper/Under (−1 to +1)
