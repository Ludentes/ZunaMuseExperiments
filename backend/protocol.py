import json
import struct
import time
import numpy as np

MSG_EEG: int = 0x01
MSG_PPG: int = 0x02
MSG_IMU: int = 0x03

_HEADER_SIZE = 5
_HEADER_STRUCT = struct.Struct("<BHH")


def encode_binary_frame(msg_type: int, data: np.ndarray) -> bytes:
    """Encode numpy array (channels x samples) into binary WebSocket frame.
    Format: [type:u8][num_channels:u16le][num_samples:u16le][data:f32le...]
    """
    num_channels, num_samples = data.shape
    header = _HEADER_STRUCT.pack(msg_type, num_channels, num_samples)
    return header + data.astype(np.float32).tobytes()


def decode_binary_frame(raw: bytes) -> tuple[int, np.ndarray]:
    """Decode binary WebSocket frame back into (msg_type, numpy array)."""
    msg_type, num_channels, num_samples = _HEADER_STRUCT.unpack_from(raw, 0)
    data = np.frombuffer(raw, dtype=np.float32, offset=_HEADER_SIZE)
    return msg_type, data.reshape(num_channels, num_samples)


def encode_metrics(metrics: dict) -> str:
    """Wrap metrics dict in JSON envelope with type and timestamp."""
    envelope = {"type": "metrics", "timestamp": time.time()}
    envelope.update(metrics)
    return json.dumps(envelope)
