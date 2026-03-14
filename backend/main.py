import asyncio
import json
import logging
import time
from pathlib import Path

import numpy as np
import websockets
from brainflow.board_shim import BoardShim
from brainflow.data_filter import DataFilter

from backend.acquisition import Acquisition
from backend.pipeline.stages.detectors import BlinkDetector
from backend.config import Config
from backend.pipeline.factory import create_default_pipeline
from backend.pipeline.serialize import frame_to_metrics
from backend.pipeline.types import CH_NAMES, Cadence, PipelineFrame
from backend.protocol import (
    MSG_EEG, MSG_PPG, MSG_IMU,
    encode_binary_frame,
    encode_metrics,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("eeg-server")
BoardShim.set_log_level(3)  # WARN only — suppress noisy BrainFlow C library logs
DataFilter.set_log_level(3)


class EEGServer:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.acq: Acquisition | None = None
        self.clients: set[websockets.WebSocketServerProtocol] = set()
        self._running = False
        self._ppg_enabled = self.config.board.enable_ppg
        self._imu_enabled = True
        self._recording = False
        self._recording_label: str = "unlabeled"
        self._recording_start: float = 0.0
        self._recording_trial_num: int = 0
        self._recording_cue_time_ms: int = 0
        self._recording_trial_duration_ms: int = 0
        self._recording_session_id: str = ""
        self._recording_eeg: list = []
        self._recording_ppg: list = []
        self._recording_imu: list = []
        self._eeg_buffer: list[np.ndarray] = []
        self._eeg_rolling: np.ndarray | None = None  # rolling 2s window
        self._eeg_rolling_max = 512  # 2s at 256Hz
        self._ppg_buffer: list[np.ndarray] = []
        self._imu_buffer: list[np.ndarray] = []
        self._latest_imu: np.ndarray | None = None  # most recent IMU chunk for FAST stages
        self._pipeline = create_default_pipeline(
            zuna_enabled=self.config.zuna.enabled,
            zuna_device=self.config.zuna.device,
            zuna_diffusion_steps=self.config.zuna.diffusion_steps,
        )

    async def start(self):
        acq = Acquisition(self.config.board)
        acq.start()
        self.acq = acq
        self._running = True
        log.info(
            "BrainFlow started — board %d, EEG %dHz",
            self.config.board.board_id,
            acq.eeg_sampling_rate,
        )

        async with websockets.serve(
            self._handle_client,
            self.config.server.host,
            self.config.server.port,
        ):
            log.info("WebSocket server on ws://%s:%d", self.config.server.host, self.config.server.port)
            await asyncio.gather(
                self._stream_loop(),
                self._metrics_loop(),
                asyncio.Future(),  # run forever
            )

    async def _handle_client(self, ws):
        self.clients.add(ws)
        log.info("Client connected (%d total)", len(self.clients))
        # Send zuna availability status to new client
        zuna_stage = self._get_zuna_stage()
        await ws.send(json.dumps({
            "type": "zuna_status",
            "available": zuna_stage is not None,
            "enabled": zuna_stage.enabled if zuna_stage else False,
        }))
        try:
            async for message in ws:
                await self._handle_command(ws, message)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(ws)
            log.info("Client disconnected (%d total)", len(self.clients))

    async def _handle_command(self, ws, message: str):  # type: ignore[reportUnusedParameter]
        try:
            cmd = json.loads(message)
        except json.JSONDecodeError:
            return

        action = cmd.get("cmd")
        if action == "enable_ppg":
            self._ppg_enabled = cmd.get("enabled", True)
        elif action == "enable_imu":
            self._imu_enabled = cmd.get("enabled", True)
        elif action == "set_filter":
            self.config.filter.highpass = cmd.get("highpass", self.config.filter.highpass)
            self.config.filter.lowpass = cmd.get("lowpass", self.config.filter.lowpass)
            self.config.filter.notch = cmd.get("notch", self.config.filter.notch)
        elif action == "start_recording":
            label = cmd.get("label", "unlabeled")
            trial_num = cmd.get("trial_num", 0)
            cue_time_ms = cmd.get("cue_time_ms", 0)
            trial_duration_ms = cmd.get("trial_duration_ms", 0)
            session_id = cmd.get("session_id", "")
            self._recording = True
            self._recording_label = label
            self._recording_start = time.time()
            self._recording_trial_num = trial_num
            self._recording_cue_time_ms = cue_time_ms
            self._recording_trial_duration_ms = trial_duration_ms
            self._recording_session_id = session_id
            self._recording_eeg.clear()
            self._recording_ppg.clear()
            self._recording_imu.clear()
            log.info("Recording started — label=%s session=%s trial=%d cue=%dms",
                     label, session_id, trial_num, cue_time_ms)
        elif action == "stop_recording":
            if self._recording:
                filepath = self._save_recording()
                self._recording = False
                self._last_saved_path = filepath
                log.info("Recording stopped — saved to %s", filepath)
                await self._broadcast_text(json.dumps({
                    "type": "recording_saved",
                    "filepath": str(filepath),
                    "label": self._recording_label,
                }))
        elif action == "enable_zuna":
            enabled = cmd.get("enabled", True)
            stage = self._get_zuna_stage()
            if stage:
                stage.enabled = enabled
                log.info("ZUNA %s", "enabled" if enabled else "disabled")
                await self._broadcast_text(json.dumps({
                    "type": "zuna_status",
                    "available": True,
                    "enabled": enabled,
                }))
            else:
                await self._broadcast_text(json.dumps({
                    "type": "zuna_status",
                    "available": False,
                    "enabled": False,
                }))
        elif action == "calibrate_blink":
            detector = self._get_blink_detector()
            if detector:
                median_peak = cmd.get("median_peak_amplitude_uv", -50.0)
                detector.set_calibrated_threshold(median_peak)
                log.info("Calibrate blink: median_peak=%.1f µV", median_peak)
        elif action == "capture_blink_sample":
            detector = self._get_blink_detector()
            if detector:
                detector.start_blink_capture(duration_s=0.7)
                asyncio.ensure_future(self._poll_blink_capture())
        elif action == "discard_last_recording":
            path = getattr(self, '_last_saved_path', None)
            if path and Path(path).exists():
                # Delete .npz and associated .fif files
                stem = Path(path).stem
                parent = Path(path).parent
                for f in parent.glob(f"{stem}*"):
                    f.unlink()
                    log.info("Discarded recording: %s", f)
                self._last_saved_path = None
                await self._broadcast_text(json.dumps({
                    "type": "recording_discarded",
                    "filepath": str(path),
                }))

    def _save_recording(self) -> Path:
        """Save recorded data to .npz and .fif files."""
        session_id = getattr(self, '_recording_session_id', '')
        # Organize by label/session_id if provided
        if session_id:
            rec_dir = Path(self.config.server.recording_dir) / self._recording_label / session_id
        else:
            rec_dir = Path(self.config.server.recording_dir) / self._recording_label
        rec_dir.mkdir(parents=True, exist_ok=True)

        ts = time.strftime("%Y%m%d_%H%M%S")
        duration = time.time() - self._recording_start
        trial_num = self._recording_trial_num
        fname = f"{self._recording_label}_t{trial_num:02d}_{ts}"

        eeg = np.concatenate(self._recording_eeg, axis=1) if self._recording_eeg else np.array([])
        ppg = np.concatenate(self._recording_ppg, axis=1) if self._recording_ppg else np.array([])
        imu = np.concatenate(self._recording_imu, axis=1) if self._recording_imu else np.array([])

        npz_path = rec_dir / f"{fname}.npz"
        np.savez(npz_path, eeg=eeg, ppg=ppg, imu=imu,
                 label=self._recording_label,
                 session_id=session_id,
                 trial_num=trial_num,
                 cue_time_ms=self._recording_cue_time_ms,
                 trial_duration_ms=self._recording_trial_duration_ms,
                 duration=duration,
                 ch_names=CH_NAMES, sfreq=256,
                 ppg_sfreq=64, imu_sfreq=52)
        log.info("Saved %s — EEG %s (%.1fs) trial=%d cue=%dms",
                 npz_path, eeg.shape if eeg.size else "empty",
                 duration, trial_num, self._recording_cue_time_ms)

        # Also save MNE .fif for ZUNA
        if eeg.size:
            try:
                import mne
                info = mne.create_info(ch_names=list(CH_NAMES), sfreq=256.0, ch_types="eeg")
                eeg_volts = eeg.astype(np.float64) * 1e-6  # µV → V
                raw = mne.io.RawArray(eeg_volts, info, verbose=False)
                montage = mne.channels.make_standard_montage("standard_1020")
                raw.set_montage(montage)
                # Add cue event as MNE annotation
                if self._recording_cue_time_ms > 0:
                    onset = self._recording_cue_time_ms / 1000.0
                    raw.set_annotations(mne.Annotations(
                        onset=[onset],
                        duration=[0.1],
                        description=[self._recording_label],
                    ))
                fif_path = rec_dir / f"{fname}_raw.fif"
                raw.save(fif_path, overwrite=True, verbose=False)
                # Save PPG/IMU companion .fif
                aux_channels = []
                aux_data = []
                aux_types = []
                if ppg.size and ppg.ndim == 2:
                    aux_channels += ["PPG_RED", "PPG_IR", "PPG_AMB"]
                    aux_types += ["misc", "misc", "misc"]
                    ppg_volts = ppg.astype(np.float64)
                    aux_data.append((ppg_volts, 64.0))
                if imu.size and imu.ndim == 2:
                    aux_channels += ["ACCEL_X", "ACCEL_Y", "ACCEL_Z",
                                     "GYRO_X", "GYRO_Y", "GYRO_Z"]
                    aux_types += ["misc"] * 6
                    imu_float = imu.astype(np.float64)
                    aux_data.append((imu_float, 52.0))
                if aux_data:
                    for adata, sfreq_aux in aux_data:
                        ch_names_aux = aux_channels[:adata.shape[0]]
                        ch_types_aux = aux_types[:adata.shape[0]]
                        aux_info = mne.create_info(
                            ch_names=ch_names_aux,
                            sfreq=sfreq_aux,
                            ch_types=ch_types_aux,
                        )
                        aux_raw = mne.io.RawArray(adata, aux_info, verbose=False)
                        suffix = "ppg" if sfreq_aux == 64.0 else "imu"
                        aux_path = rec_dir / f"{fname}_{suffix}.fif"
                        aux_raw.save(aux_path, overwrite=True, verbose=False)
                        aux_channels = aux_channels[adata.shape[0]:]
                        aux_types = aux_types[adata.shape[0]:]
                log.info("Saved %s (MNE .fif)", fif_path)
            except ImportError:
                log.warning("MNE not installed — skipping .fif export")

        return npz_path

    def _get_zuna_stage(self):
        """Find ZunaStage in pipeline if it exists."""
        for stage in self._pipeline.stages:
            if stage.name == "zuna_stage":
                return stage
        return None

    def _get_blink_detector(self) -> BlinkDetector | None:
        """Find BlinkDetector in pipeline if it exists."""
        for stage in self._pipeline.stages:
            if isinstance(stage, BlinkDetector):
                return stage
        return None

    async def _poll_blink_capture(self) -> None:
        """Poll BlinkDetector until capture window closes, then broadcast the result."""
        for _ in range(20):  # up to 1s in 50ms steps
            await asyncio.sleep(0.05)
            detector = self._get_blink_detector()
            if detector:
                result = detector.get_capture_result()
                if result is not None:
                    await self._broadcast_text(json.dumps({
                        "type": "bci_event",
                        "kind": "blink_sample",
                        "confidence": 1.0,
                        "channel": "AF7+AF8",
                        "timestamp": time.time(),
                        "metadata": result,
                    }))
                    return

    async def _broadcast_binary(self, data: bytes):
        if not self.clients:
            return
        websockets.broadcast(self.clients, data)

    async def _broadcast_text(self, data: str):
        if not self.clients:
            return
        websockets.broadcast(self.clients, data)

    async def _stream_loop(self):
        """Poll BrainFlow and broadcast binary frames at ~60fps.

        Monitors stream health and triggers reconnection if data stops arriving.
        """
        interval = self.config.server.eeg_batch_interval
        watchdog_check_interval = 5.0  # check stream health every 5s
        last_watchdog = time.time()

        while self._running:
            if self.acq is None:
                await asyncio.sleep(interval)
                continue

            # Watchdog: detect stream drops and attempt reconnect
            now = time.time()
            if now - last_watchdog > watchdog_check_interval:
                last_watchdog = now
                if self.acq.is_streaming and not self.acq.stream_healthy:
                    log.warning("Stream watchdog: no data for %.1fs — reconnecting",
                                self.acq.seconds_since_last_data)
                    await self._broadcast_text(json.dumps({
                        "type": "connection_status",
                        "status": "reconnecting",
                    }))
                    # Run reconnect in executor to avoid blocking event loop
                    loop = asyncio.get_event_loop()
                    success = await loop.run_in_executor(None, self.acq.reconnect)
                    status = "connected" if success else "disconnected"
                    log.info("Reconnect result: %s", status)
                    await self._broadcast_text(json.dumps({
                        "type": "connection_status",
                        "status": status,
                    }))
                    if not success:
                        await asyncio.sleep(5)  # back off before next attempt
                    continue

            eeg = self.acq.get_eeg_data()
            if eeg is not None and eeg.shape[1] > 0:
                self._eeg_buffer.append(eeg)
                if self._recording:
                    self._recording_eeg.append(eeg)
                await self._broadcast_binary(encode_binary_frame(MSG_EEG, eeg))

                # Run FAST stages for event detection
                fast_frame = PipelineFrame(
                    eeg=eeg, ppg=None, imu=self._latest_imu,
                    timestamp=time.time(),
                )
                self._pipeline.run(Cadence.FAST, fast_frame)
                if fast_frame.events:
                    for event in fast_frame.events:
                        await self._broadcast_text(json.dumps({
                            "type": "bci_event",
                            "kind": event.kind,
                            "confidence": event.confidence,
                            "channel": event.channel,
                            "timestamp": event.timestamp,
                            "metadata": event.metadata,
                        }))

            if self._ppg_enabled:
                ppg = self.acq.get_ppg_data()
                if ppg is not None and ppg.shape[1] > 0:
                    self._ppg_buffer.append(ppg)
                    if self._recording:
                        self._recording_ppg.append(ppg)
                    await self._broadcast_binary(encode_binary_frame(MSG_PPG, ppg))

            if self._imu_enabled:
                imu = self.acq.get_imu_data()
                if imu is not None and imu.shape[1] > 0:
                    self._latest_imu = imu
                    self._imu_buffer.append(imu)
                    if self._recording:
                        self._recording_imu.append(imu)
                    await self._broadcast_binary(encode_binary_frame(MSG_IMU, imu))

            await asyncio.sleep(interval)

    async def _metrics_loop(self):
        """Compute and broadcast derived metrics at configured rate.

        EEG uses a sliding window (2s of data, updated every 0.5s) for stable
        PSD estimates with frequent updates. PPG/IMU still use accumulate-and-clear
        since their stages manage their own rolling state.
        """
        interval = self.config.server.metrics_interval
        while self._running:
            await asyncio.sleep(interval)

            # EEG: append new chunks to rolling buffer, keep last 2s
            if self._eeg_buffer:
                new_eeg = np.concatenate(self._eeg_buffer, axis=1)
                self._eeg_buffer.clear()
                if self._eeg_rolling is None:
                    self._eeg_rolling = new_eeg
                else:
                    self._eeg_rolling = np.concatenate(
                        [self._eeg_rolling, new_eeg], axis=1
                    )
                # Trim to max window size
                if self._eeg_rolling.shape[1] > self._eeg_rolling_max:
                    self._eeg_rolling = self._eeg_rolling[:, -self._eeg_rolling_max:]

            eeg = self._eeg_rolling  # use full 2s window, don't clear

            ppg = (
                np.concatenate(self._ppg_buffer, axis=1)
                if self._ppg_buffer
                else None
            )
            imu = (
                np.concatenate(self._imu_buffer, axis=1)
                if self._imu_buffer
                else None
            )

            self._ppg_buffer.clear()
            self._imu_buffer.clear()

            frame = PipelineFrame(
                eeg=eeg, ppg=ppg, imu=imu,
                timestamp=time.time(),
            )
            # Run in executor to avoid blocking the event loop during
            # potentially slow stages (e.g. ZUNA GPU inference ~1-5s)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._pipeline.run, Cadence.SLOW, frame)
            metrics = frame_to_metrics(frame)

            from backend.pipeline.stages.features import SignalQualityResult
            sq = frame.get(SignalQualityResult)
            if sq:
                detector = self._get_blink_detector()
                if detector:
                    frontal_avg = (sq.quality.get("AF7", 0) + sq.quality.get("AF8", 0)) / 2
                    detector.set_signal_quality(frontal_avg)

            metrics["session"] = {
                "recording": self._recording,
                "label": self._recording_label if self._recording else None,
                "duration_sec": round(time.time() - self._recording_start, 1) if self._recording else 0,
            }

            if metrics:
                log.debug("Broadcasting metrics keys: %s", list(metrics.keys()))
                await self._broadcast_text(encode_metrics(metrics))

    def shutdown(self):
        self._running = False
        if self.acq:
            self.acq.stop()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="EEG Dashboard Backend")
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Use synthetic board (no hardware needed)",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mac", type=str, default="", help="Muse MAC address (e.g. 00:55:DA:B8:2B:1B)")
    parser.add_argument("--zuna", action="store_true", help="Enable ZUNA 23ch superresolution (requires CUDA GPU)")
    args = parser.parse_args()

    config = Config()
    config.server.port = args.port
    config.board.mac_address = args.mac
    if args.synthetic:
        config.board.board_id = -1  # SYNTHETIC_BOARD
        config.board.enable_ppg = False
    if args.zuna:
        config.zuna.enabled = True

    server = EEGServer(config)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        log.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
