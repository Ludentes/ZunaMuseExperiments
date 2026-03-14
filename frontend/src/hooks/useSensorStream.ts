import { useCallback, useRef, useState } from "react";
import useWebSocket, { ReadyState } from "react-use-websocket";
import {
  MSG_EEG, MSG_PPG,
  EEG_CHANNELS, PPG_CHANNELS,
  decodeBinaryFrame,
  getChannel,
  type BciEvent,
} from "../lib/protocol";
import { RingBuffer } from "../lib/ringBuffer";

const WS_URL = "ws://localhost:8765";

// 5 seconds of data per channel
const EEG_BUFFER_SIZE = 256 * 5;   // 1280 samples
const PPG_BUFFER_SIZE = 64 * 5;    // 320 samples

export interface SensorBuffers {
  eeg: RingBuffer[];    // 4 channels
  ppg: RingBuffer[];    // 3 channels (IR, Red, Ambient)
}

export interface ZunaStatus {
  available: boolean;
  enabled: boolean;
}

export function useSensorStream() {
  const buffersRef = useRef<SensorBuffers>({
    eeg: Array.from({ length: EEG_CHANNELS }, () => new RingBuffer(EEG_BUFFER_SIZE)),
    ppg: Array.from({ length: PPG_CHANNELS }, () => new RingBuffer(PPG_BUFFER_SIZE)),
  });

  const metricsRef = useRef<string | null>(null);
  const eventsRef = useRef<BciEvent[]>([]);
  const [zunaStatus, setZunaStatus] = useState<ZunaStatus>({ available: false, enabled: false });

  const { readyState, sendJsonMessage, lastMessage } = useWebSocket(WS_URL, {
    onMessage: (event) => {
      if (event.data instanceof Blob) {
        // Binary frame — read into ArrayBuffer
        event.data.arrayBuffer().then((buffer) => {
          const frame = decodeBinaryFrame(buffer);
          const buffers = buffersRef.current;

          if (frame.type === MSG_EEG) {
            for (let ch = 0; ch < Math.min(frame.channels, EEG_CHANNELS); ch++) {
              buffers.eeg[ch].push(getChannel(frame, ch));
            }
          } else if (frame.type === MSG_PPG) {
            for (let ch = 0; ch < Math.min(frame.channels, PPG_CHANNELS); ch++) {
              buffers.ppg[ch].push(getChannel(frame, ch));
            }
          }
          // IMU: not buffered for waveform, only used via metrics JSON
        });
      } else {
        // JSON frame — check for zuna_status or metrics
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "zuna_status") {
            setZunaStatus({ available: msg.available, enabled: msg.enabled });
          } else if (msg.type === "bci_event") {
            eventsRef.current = [...eventsRef.current.slice(-49), msg as BciEvent];
          } else {
            metricsRef.current = event.data;
          }
        } catch {
          metricsRef.current = event.data;
        }
      }
    },
    shouldReconnect: () => true,
    reconnectInterval: 2000,
  });

  const sendCommand = useCallback(
    (cmd: Record<string, unknown>) => {
      sendJsonMessage(cmd);
    },
    [sendJsonMessage],
  );

  return {
    buffers: buffersRef,
    metricsRef,
    eventsRef,
    lastMessage,
    readyState,
    isConnected: readyState === ReadyState.OPEN,
    sendCommand,
    zunaStatus,
  };
}
