"""pytest fixtures for lsl_test."""
import sys
from pathlib import Path

import pytest

# Allow importing from thymio_control
_thymio_path = Path(__file__).parent.parent / "thymio_control"
if str(_thymio_path) not in sys.path:
    sys.path.insert(0, str(_thymio_path))


@pytest.fixture
def edf_path() -> Path:
    base = Path(__file__).parent
    # Try mock_data first, fall back to real enobio_recodes for development
    candidate = base / "mock_data" / "20260408111446_Patient01.edf"
    if candidate.exists():
        return candidate
    return base.parent / "enobio_recodes" / "20260408111446_Patient01.edf"


@pytest.fixture
def easy_path() -> Path:
    return Path(__file__).parent.parent / "enobio_recodes" / "20260408111446_Patient01.easy"


@pytest.fixture
def info_path() -> Path:
    return Path(__file__).parent.parent / "enobio_recodes" / "20260408111446_Patient01.info"


@pytest.fixture
def edf_reader(edf_path: Path):
    """Create and automatically close an EdfReader."""
    from lsl_test.edf_reader import EdfReader
    reader = EdfReader(edf_path)
    yield reader
    reader.close()