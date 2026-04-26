"""pytest fixtures for lsl_test."""
import gc
import sys
import time
from pathlib import Path

import pytest

# Allow importing from thymio_control
_thymio_path = Path(__file__).parent.parent / "thymio_control"
if str(_thymio_path) not in sys.path:
    sys.path.insert(0, str(_thymio_path))


@pytest.fixture(autouse=True)
def _cleanup_lsl_outlets():
    """Force GC after each LSL test to release stale StreamOutlets."""
    yield
    gc.collect()
    time.sleep(0.3)  # Let LSL daemon detect closed outlets


@pytest.fixture
def edf_path() -> Path:
    pytest.importorskip("pyedflib", reason="pyedflib not installed")
    base = Path(__file__).parent
    # Try mock_data first, fall back to real enobio_recodes for development
    candidate = base / "mock_data" / "20260408111446_Patient01.edf"
    if candidate.exists():
        return candidate
    fallback = base.parent / "enobio_recodes" / "20260408111446_Patient01.edf"
    if fallback.exists():
        return fallback
    pytest.skip(
        "No EDF file found — place one in lsl_test/mock_data/ or enobio_recodes/ to run this test"
    )


@pytest.fixture
def easy_path() -> Path:
    path = Path(__file__).parent.parent / "enobio_recodes" / "20260408111446_Patient01.easy"
    if not path.exists():
        pytest.skip("enobio_recodes/20260408111446_Patient01.easy not found")
    return path


@pytest.fixture
def info_path() -> Path:
    path = Path(__file__).parent.parent / "enobio_recodes" / "20260408111446_Patient01.info"
    if not path.exists():
        pytest.skip("enobio_recodes/20260408111446_Patient01.info not found")
    return path


@pytest.fixture
def edf_reader(edf_path: Path):
    """Create and automatically close an EdfReader."""
    pytest.importorskip("pyedflib", reason="pyedflib not installed")
    from lsl_test.edf_reader import EdfReader
    reader = EdfReader(edf_path)
    yield reader
    reader.close()