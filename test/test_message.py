import json
import pytest
from protocol.message import Message, ProtocolError


def test_message_serialization():
    msg = Message(
        type="LETTER",
        request_id=1,
        session_id="session-123",
        payload={"letter": "E"}
    )
    raw_bytes = msg.serialize()
    
    assert isinstance(raw_bytes, bytes)
    decoded = json.loads(raw_bytes.decode("utf-8"))
    assert decoded["type"] == "LETTER"
    assert decoded["request_id"] == 1
    assert decoded["session_id"] == "session-123"
    assert decoded["payload"] == {"letter": "E"}


def test_message_deserialization_valid():
    raw_json = b'{"type": "HELLO", "request_id": 42, "session_id": null, "payload": {"player_name": "Bob"}}'
    msg = Message.deserialize(raw_json)

    assert msg.type == "HELLO"
    assert msg.request_id == 42
    assert msg.session_id is None
    assert msg.payload == {"player_name": "Bob"}


def test_roundtrip_consistency():
    original = Message(
        type="STATE",
        request_id=5,
        session_id="abc-999",
        payload={"masked_word": "_ E _ E", "errors_left": 4}
    )
    serialized = original.serialize()
    restored = Message.deserialize(serialized)

    assert original == restored


def test_deserialize_invalid_utf8():
    with pytest.raises(ProtocolError):
        Message.deserialize(b"\xff\xfe\x00")


def test_deserialize_invalid_json():
    with pytest.raises(ProtocolError):
        Message.deserialize(b'{"type": "LETTER", "request_id": ')


def test_deserialize_not_a_dict():
    with pytest.raises(ProtocolError):
        Message.deserialize(b'["HELLO", 1, 2]')
    with pytest.raises(ProtocolError):
        Message.deserialize(b'"chaine simple"')


def test_deserialize_missing_mandatory_fields():
    # Manque request_id
    with pytest.raises(ProtocolError):
        Message.deserialize(b'{"type": "NEW_GAME"}')
    
    # Manque type
    with pytest.raises(ProtocolError):
        Message.deserialize(b'{"request_id": 1}')


def test_deserialize_extra_unexpected_keys_ignored():
    # Clé inconnue 'extra_key' qui ne doit pas faire crasher le serveur
    raw = b'{"type": "NEW_GAME", "request_id": 2, "extra_key": 1234, "payload": {}}'
    msg = Message.deserialize(raw)
    assert msg.type == "NEW_GAME"
    assert msg.request_id == 2