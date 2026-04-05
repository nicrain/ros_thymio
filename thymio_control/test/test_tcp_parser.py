import pytest

from thymio_control.eeg_control_pipeline import _parse_sod_packet, extract_tcp_feature


def test_tcp_feature_extraction():
    packet = "SOD12;3;0.25;0.75;1.1;2.2EOD"

    feature = extract_tcp_feature(packet)

    assert feature == pytest.approx(0.75)


def test_tcp_feature_extraction_missing_field():
    packet = "SOD12;3;0.25EOD"

    with pytest.raises(IndexError):
        extract_tcp_feature(packet)


def test_tcp_feature_extraction_non_numeric_field():
    packet = "SOD12;3;0.25;not-a-number;1.1;2.2EOD"

    with pytest.raises(ValueError):
        extract_tcp_feature(packet)


def test_parse_sod_packet_exposes_feature_metric():
    packet = "SOD12;3;0.25;0.75;1.1;2.2;0.0;-1.0EOD"

    metrics = _parse_sod_packet(packet)

    assert metrics["feature"] == pytest.approx(0.75)
    assert metrics["movement"] == pytest.approx(0.25)