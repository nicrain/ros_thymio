from pathlib import Path

import pytest

from thymio_control.enobio_file_reader import EnobioFileReader


def _mock_paths() -> tuple[Path, Path]:
    base_path = Path(__file__).resolve().parent / "mock_data"
    return base_path / "enobio_small.info", base_path / "enobio_small.easy"


def test_enobio_file_reader_parses_metadata_and_samples():
    info_path, easy_path = _mock_paths()
    reader = EnobioFileReader(info_path, easy_path)

    metadata = reader.read_info()
    samples = reader.read_easy_samples()

    assert metadata.channels == 20
    assert metadata.sample_rate == 500
    assert len(samples) == 2
    assert len(samples[0]) == 22
    assert samples[0][0] == pytest.approx(1.0)
    assert samples[0][-1] == pytest.approx(1000.0)


def test_enobio_file_reader_raises_on_missing_metadata(tmp_path: Path):
    base_path = Path(__file__).resolve().parent / "mock_data"
    bad_info_path = tmp_path / "enobio_missing_fields.info"
    bad_info_path.write_text("Device class: Enobio20\n", encoding="utf-8")

    reader = EnobioFileReader(bad_info_path, base_path / "enobio_small.easy")

    with pytest.raises(ValueError):
        reader.read_info()