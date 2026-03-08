from dataclasses import dataclass, field


@dataclass
class BoardConfig:
    board_id: int = 38  # MUSE_2_BOARD
    serial_port: str = ""
    mac_address: str = ""
    enable_ppg: bool = True  # send "p50" to enable PPG + 5th EEG ch


@dataclass
class FilterConfig:
    highpass: float = 0.5
    lowpass: float = 45.0
    notch: float = 50.0  # 0 to disable


@dataclass
class ServerConfig:
    host: str = "localhost"
    port: int = 8765
    eeg_batch_interval: float = 0.0625  # 16ms (~60fps)
    metrics_interval: float = 0.5  # 2Hz
    recording_dir: str = "recordings"


@dataclass
class Config:
    board: BoardConfig = field(default_factory=BoardConfig)
    filter: FilterConfig = field(default_factory=FilterConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
