import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import websockets

from backend.acquisition import Acquisition
from backend.config import Config
from backend.processing import build_metrics
from backend.protocol import (
    MSG_EEG, MSG_PPG, MSG_IMU,
    encode_binary_frame,
    encode_metrics,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("eeg-server")


class EEGServer:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.acq: Acquisition | None = None
        self.clients: set[websockets.WebSocketServerProtocol] = set()
        self._running = False
        self._ppg_enabled = self.config.board.enable_ppg
        self._imu_enabled = True
        self._recording = False
        self._eeg_buffer = []
        self._ppg_buffer = []
        self._imu_buffer = []

    async def start(self):
        self.acq = Acquisition(self.config.board)
        self.acq.start()
        self._running = True
        log.info(
            "BrainFlow started — board %d, EEG %dHz",
            self.config.board.board_id,
            self.acq.eeg_sampling_rate,
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
        try:
            async for message in ws:
                await self._handle_command(ws, message)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(ws)
            log.info("Client disconnected (%d total)", len(self.clients))

    async def _handle_command(self, ws, message: str):
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
            self._recording = True
            log.info("Recording started")
        elif action == "stop_recording":
            self._recording = False
            log.info("Recording stopped")

    async def _broadcast_binary(self, data: bytes):
        if not self.clients:
            return
        websockets.broadcast(self.clients, data)

    async def _broadcast_text(self, data: str):
        if not self.clients:
            return
        websockets.broadcast(self.clients, data)

    async def _stream_loop(self):
        """Poll BrainFlow and broadcast binary frames at ~60fps."""
        interval = self.config.server.eeg_batch_interval
        while self._running:
            if self.acq is None:
                await asyncio.sleep(interval)
                continue

            eeg = self.acq.get_eeg_data()
            if eeg is not None and eeg.shape[1] > 0:
                self._eeg_buffer.append(eeg)
                await self._broadcast_binary(encode_binary_frame(MSG_EEG, eeg))

            if self._ppg_enabled:
                ppg = self.acq.get_ppg_data()
                if ppg is not None and ppg.shape[1] > 0:
                    self._ppg_buffer.append(ppg)
                    await self._broadcast_binary(encode_binary_frame(MSG_PPG, ppg))

            if self._imu_enabled:
                imu = self.acq.get_imu_data()
                if imu is not None and imu.shape[1] > 0:
                    self._imu_buffer.append(imu)
                    await self._broadcast_binary(encode_binary_frame(MSG_IMU, imu))

            await asyncio.sleep(interval)

    async def _metrics_loop(self):
        """Compute and broadcast derived metrics at configured rate."""
        interval = self.config.server.metrics_interval
        while self._running:
            await asyncio.sleep(interval)

            # Concatenate buffered data for metrics computation
            eeg = (
                np.concatenate(self._eeg_buffer, axis=1)
                if self._eeg_buffer
                else None
            )
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

            # Clear buffers
            self._eeg_buffer.clear()
            self._ppg_buffer.clear()
            self._imu_buffer.clear()

            sr = self.acq.eeg_sampling_rate if self.acq else 256
            metrics = build_metrics(eeg, ppg, imu, sr)
            if metrics:
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
    args = parser.parse_args()

    config = Config()
    config.server.port = args.port
    if args.synthetic:
        config.board.board_id = -1  # SYNTHETIC_BOARD
        config.board.enable_ppg = False

    server = EEGServer(config)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        log.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
