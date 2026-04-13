import socket

from thymio_control.eeg_control_pipeline import TcpClientJsonAdapter
import thymio_control.eeg_control_pipeline as pipeline


class _FakeSocket:
    def __init__(self, recv_script):
        self._recv_script = list(recv_script)
        self.closed = False

    def setblocking(self, _value):
        return None

    def close(self):
        self.closed = True

    def recv(self, _size):
        if not self._recv_script:
            raise BlockingIOError

        event = self._recv_script.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


class _ConnectionFactory:
    def __init__(self, sockets):
        self._sockets = list(sockets)
        self.calls = 0

    def __call__(self, *_args, **_kwargs):
        self.calls += 1
        if not self._sockets:
            raise OSError("no more fake sockets")
        return self._sockets.pop(0)


def test_tcp_client_adapter_returns_none_without_complete_packet(monkeypatch):
    fake_sock = _FakeSocket([b"SOD1;1;0.1;0.2", BlockingIOError()])
    factory = _ConnectionFactory([fake_sock])
    monkeypatch.setattr(socket, "create_connection", factory)

    adapter = TcpClientJsonAdapter("127.0.0.1", 6001, reconnect_sec=0.1)

    assert adapter.read_frame() is None


def test_tcp_client_adapter_parses_last_valid_packet_when_multiple_arrive(monkeypatch):
    payload = (
        b"noise"
        b"SOD1;1;0.1;0.2;0.0;-1.0EOD"
        b"SOD2;1;0.3;0.8;0.0;-1.0EOD"
    )
    fake_sock = _FakeSocket([payload, BlockingIOError()])
    factory = _ConnectionFactory([fake_sock])
    monkeypatch.setattr(socket, "create_connection", factory)

    adapter = TcpClientJsonAdapter("127.0.0.1", 6001, reconnect_sec=0.1)
    frame = adapter.read_frame()

    assert frame is not None
    assert frame.metrics["packet_no"] == 2.0
    assert frame.metrics["movement"] == 0.3
    assert frame.metrics["feature"] == 0.8


def test_tcp_client_adapter_reassembles_packet_across_reads(monkeypatch):
    fake_sock = _FakeSocket(
        [
            b"SOD7;1;0.9;0.4",
            BlockingIOError(),
            b";0.0;-1.0EOD",
            BlockingIOError(),
        ]
    )
    factory = _ConnectionFactory([fake_sock])
    monkeypatch.setattr(socket, "create_connection", factory)

    adapter = TcpClientJsonAdapter("127.0.0.1", 6001, reconnect_sec=0.1)

    assert adapter.read_frame() is None

    frame = adapter.read_frame()
    assert frame is not None
    assert frame.metrics["packet_no"] == 7.0
    assert frame.metrics["feature"] == 0.4


def test_tcp_client_adapter_reconnects_after_disconnect(monkeypatch):
    first_sock = _FakeSocket([b"", BlockingIOError()])
    second_sock = _FakeSocket([b"SOD9;1;0.2;0.6;0.0;-1.0EOD", BlockingIOError()])
    factory = _ConnectionFactory([first_sock, second_sock])
    monkeypatch.setattr(socket, "create_connection", factory)
    now = {"value": 1000.0}
    monkeypatch.setattr(pipeline.time, "time", lambda: now["value"])

    adapter = TcpClientJsonAdapter("127.0.0.1", 6001, reconnect_sec=0.0)

    assert adapter.read_frame() is None

    now["value"] += 0.2

    frame = adapter.read_frame()
    assert frame is not None
    assert frame.metrics["packet_no"] == 9.0
    assert frame.metrics["feature"] == 0.6
    assert factory.calls >= 2
