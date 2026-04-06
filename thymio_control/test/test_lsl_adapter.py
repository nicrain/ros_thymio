import threading
import time

import pytest

pylsl = pytest.importorskip("pylsl")

from pylsl import StreamInfo, StreamOutlet

from thymio_control.eeg_control_pipeline import LslAdapter


def test_lsl_adapter_reads_mock_stream():
    info = StreamInfo("thymio_test_eeg", "EEG", 4, 10, "float32", "thymio_test_lsl")
    outlet = StreamOutlet(info)

    adapter = LslAdapter(
        stream_type="EEG",
        timeout=2.0,
        channel_map={"alpha": 0, "theta": 1, "beta": 2, "left_alpha": 3},
    )

    def push_sample() -> None:
        time.sleep(0.1)
        outlet.push_sample([0.11, 0.22, 0.33, 0.44])

    thread = threading.Thread(target=push_sample, daemon=True)
    thread.start()

    deadline = time.time() + 3.0
    frame = None
    while time.time() < deadline:
        frame = adapter.read_frame()
        if frame is not None:
            break
        time.sleep(0.05)

    assert frame is not None
    assert frame.source == "lsl"
    assert frame.metrics["alpha"] == pytest.approx(0.11)
    assert frame.metrics["theta"] == pytest.approx(0.22)
    assert frame.metrics["beta"] == pytest.approx(0.33)
    assert frame.metrics["left_alpha"] == pytest.approx(0.44)


def test_lsl_adapter_raises_when_stream_type_missing():
    with pytest.raises(RuntimeError):
        LslAdapter(
            stream_type="NOT_THYMIO",
            timeout=0.2,
            channel_map={"alpha": 0},
        )