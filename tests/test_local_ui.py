from __future__ import annotations

import pytest

from comfyui_py_workflow.local_ui import (
    SingleInstanceHTTPServer,
    StudioRequestHandler,
    parse_byte_range,
)


def test_local_ui_port_is_single_instance() -> None:
    first = SingleInstanceHTTPServer(("127.0.0.1", 0), StudioRequestHandler)
    host, port = first.server_address
    try:
        with pytest.raises(OSError):
            second = SingleInstanceHTTPServer((host, port), StudioRequestHandler)
            second.server_close()
    finally:
        first.server_close()


def test_byte_ranges_include_suffix_and_open_ended_forms() -> None:
    assert parse_byte_range(None, 1000) is None
    assert parse_byte_range("bytes=100-199", 1000) == (100, 199)
    assert parse_byte_range("bytes=900-", 1000) == (900, 999)
    assert parse_byte_range("bytes=-100", 1000) == (900, 999)
    assert parse_byte_range("bytes=-2000", 1000) == (0, 999)


@pytest.mark.parametrize("value", ["bytes=-0", "bytes=1000-", "bytes=9-2", "items=1-2"])
def test_invalid_byte_ranges_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        parse_byte_range(value, 1000)
