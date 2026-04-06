"""Utilities for reading Enobio offline recordings.

The reader is intentionally small and deterministic so it can be used by
tests and by the future file playback adapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


@dataclass(frozen=True)
class EnobioRecordingMetadata:
    channels: int
    sample_rate: int


class EnobioFileReader:
    def __init__(self, info_path: str | Path, easy_path: str | Path) -> None:
        self.info_path = Path(info_path)
        self.easy_path = Path(easy_path)

    def read_info(self) -> EnobioRecordingMetadata:
        if not self.info_path.exists():
            raise FileNotFoundError(f"Enobio info file not found: {self.info_path}")

        content = self.info_path.read_text(encoding="utf-8")
        channels = self._extract_first_int(content, [
            r"Number of EEG channels:\s*(\d+)",
            r"Total number of channels:\s*(\d+)",
        ])
        sample_rate = self._extract_first_int(content, [
            r"EEG sampling rate:\s*(\d+)\s*Samples/second",
            r"Sample Rate:\s*(\d+)",
        ])
        return EnobioRecordingMetadata(channels=channels, sample_rate=sample_rate)

    def read_easy_samples(self) -> List[List[float]]:
        if not self.easy_path.exists():
            raise FileNotFoundError(f"Enobio easy file not found: {self.easy_path}")

        samples: List[List[float]] = []
        with self.easy_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    samples.append([float(value) for value in stripped.split()])
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid numeric value in {self.easy_path} at line {line_number}: {stripped!r}"
                    ) from exc

        return samples

    def iter_easy_samples(self) -> Iterable[List[float]]:
        for sample in self.read_easy_samples():
            yield sample

    @staticmethod
    def _extract_first_int(content: str, patterns: list[str]) -> int:
        for pattern in patterns:
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))
        raise ValueError(f"Required Enobio metadata not found for patterns: {patterns}")