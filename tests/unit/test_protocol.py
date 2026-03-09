from renderdoc_mcp.protocol import decode_message, encode_message


def test_protocol_message_round_trip() -> None:
    payload = {"type": "request", "id": "abc", "method": "ping", "params": {"x": 1}}
    text = encode_message(payload).decode("utf-8")
    assert decode_message(text) == payload
