from renderdoc_mcp.uri import decode_capture_path, encode_capture_path


def test_capture_path_round_trip() -> None:
    path = r"C:\captures\sample.rdc"
    assert decode_capture_path(encode_capture_path(path)) == path
