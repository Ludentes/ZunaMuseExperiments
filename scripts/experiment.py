"""Lightweight experiment tracking.

Usage:
    from scripts.experiment import Experiment

    with Experiment("blink-detector-v5", tags=["blink", "hf-window"]) as exp:
        exp.param("threshold_uv", -75)
        exp.param("max_hf_ratio", 3.5)
        exp.param("hf_window", 128)
        # ... run evaluation ...
        exp.metric("precision", 0.95)
        exp.metric("recall", 0.95)
        exp.metric("f1", 0.95)
        exp.metric("fp_rest", 0)
        exp.artifact("sweep.txt", sweep_output)

Saves to experiments/<timestamp>-<name>/:
    config.json   — params, tags, git info
    results.json  — metrics
    *.txt / *.npy  — artifacts

Appends summary to experiments/registry.csv.
"""
from __future__ import annotations

import csv
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


EXPERIMENTS_DIR = Path(__file__).parent.parent / "experiments"
REGISTRY_PATH = EXPERIMENTS_DIR / "registry.csv"

REGISTRY_FIELDS = [
    "id", "name", "timestamp", "git_sha", "tags",
    # Metrics are appended dynamically
]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent.parent,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _git_dirty() -> bool:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=Path(__file__).parent.parent,
            text=True,
        ).strip()
        return len(out) > 0
    except Exception:
        return False


class Experiment:
    """Context manager for tracking one experiment run."""

    def __init__(self, name: str, tags: list[str] | None = None):
        self.name = name
        self.tags = tags or []
        self.timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.id = f"{self.timestamp}-{name}"
        self.dir = EXPERIMENTS_DIR / self.id
        self._params: dict[str, object] = {}
        self._metrics: dict[str, float] = {}
        self._start_time: float = 0.0

    def __enter__(self) -> Experiment:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._start_time = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):  # type: ignore[override]
        elapsed = time.monotonic() - self._start_time
        self._save_config(elapsed, error=str(exc_val) if exc_val else None)
        self._save_results()
        self._append_registry()
        print(f"Experiment saved: {self.dir}")

    def param(self, key: str, value: object) -> None:
        self._params[key] = value

    def params(self, d: dict[str, object]) -> None:
        self._params.update(d)

    def metric(self, key: str, value: float) -> None:
        self._metrics[key] = value

    def metrics(self, d: dict[str, float]) -> None:
        self._metrics.update(d)

    def artifact(self, filename: str, content: str | bytes) -> Path:
        """Save a text or binary artifact."""
        path = self.dir / filename
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)
        return path

    def _save_config(self, elapsed: float, error: str | None) -> None:
        config = {
            "id": self.id,
            "name": self.name,
            "timestamp": self.timestamp,
            "tags": self.tags,
            "git_sha": _git_sha(),
            "git_dirty": _git_dirty(),
            "params": self._params,
            "elapsed_s": round(elapsed, 2),
        }
        if error:
            config["error"] = error
        (self.dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")

    def _save_results(self) -> None:
        (self.dir / "results.json").write_text(
            json.dumps(self._metrics, indent=2) + "\n"
        )

    def _append_registry(self) -> None:
        row = {
            "id": self.id,
            "name": self.name,
            "timestamp": self.timestamp,
            "git_sha": _git_sha(),
            "tags": ";".join(self.tags),
        }
        row.update({k: str(v) for k, v in self._metrics.items()})

        file_exists = REGISTRY_PATH.exists()
        existing_fields: list[str] = []
        if file_exists:
            with open(REGISTRY_PATH) as f:
                reader = csv.DictReader(f)
                existing_fields = list(reader.fieldnames or [])

        # Merge fields: existing + any new metric keys
        all_fields = list(existing_fields) if existing_fields else list(REGISTRY_FIELDS)
        for key in row:
            if key not in all_fields:
                all_fields.append(key)

        # If new columns were added, rewrite the file
        if existing_fields and set(all_fields) != set(existing_fields):
            rows = []
            with open(REGISTRY_PATH) as f:
                rows = list(csv.DictReader(f))
            with open(REGISTRY_PATH, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=all_fields)
                writer.writeheader()
                for r in rows:
                    writer.writerow(r)
                writer.writerow(row)
        else:
            with open(REGISTRY_PATH, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=all_fields)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
