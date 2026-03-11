export const MSG_EEG = 0x01;
export const MSG_PPG = 0x02;
export const MSG_IMU = 0x03;

export const EEG_CHANNELS = 4;
export const PPG_CHANNELS = 3;
export const IMU_CHANNELS = 6;

export const CHANNEL_NAMES = ["TP9", "AF7", "AF8", "TP10"] as const;

export interface DecodedFrame {
  type: number;
  channels: number;
  samples: number;
  data: Float32Array; // flat: channels × samples, row-major
}

export function decodeBinaryFrame(buffer: ArrayBuffer): DecodedFrame {
  const view = new DataView(buffer);
  const type = view.getUint8(0);
  const channels = view.getUint16(1, true); // little-endian
  const samples = view.getUint16(3, true);
  // Copy data past 5-byte header (offset 5 is not 4-byte aligned, so can't create a view)
  const data = new Float32Array(buffer.slice(5));
  return { type, channels, samples, data };
}

/** Extract one channel from a decoded frame (row-major layout). */
export function getChannel(frame: DecodedFrame, channelIndex: number): Float32Array {
  const offset = channelIndex * frame.samples;
  return frame.data.subarray(offset, offset + frame.samples);
}

export interface BandPowers {
  mode: "4ch" | "23ch";
  channels: Record<string, Record<string, number>>;
}

export interface Metrics {
  type: "metrics";
  timestamp: number;
  band_powers?: BandPowers;
  eeg?: {
    band_powers: Record<string, number[]>;
    theta_beta_ratio: number[];
    frontal_alpha_asymmetry: number;
    signal_quality: Record<string, number>;
    fit_status: "good" | "adjust" | "poor";
  };
  ppg?: {
    heart_rate_bpm: number;
    spo2_percent: number;
    hrv_rmssd_ms: number;
  };
  imu?: {
    head_movement: number;
    head_pose: { pitch: number; roll: number };
    motion_artifact: boolean;
    jaw_clench: boolean;
  };
  brain?: {
    concentration: number;
    relaxation: number;
  };
  eyes_closed?: {
    active: boolean;
    alpha_ratio: number;
    baseline_alpha: number;
  };
  headband?: {
    state: "ready" | "fitting" | "headband_off";
    seconds_in_state: number;
  };
  session?: {
    recording: boolean;
    label: string | null;
    duration_sec: number;
  };
}
