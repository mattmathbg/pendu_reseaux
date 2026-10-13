from protocol.message import Message, ProtocolError
import json


msg = Message(
     type="LETTER",
     request_id=1,
     session_id="session-123",
     payload={"letter": "E"}
)
raw_bytes = msg.serialize()

print(f"Serialized bytes: {raw_bytes}")

assert isinstance(raw_bytes, bytes)
decoded = json.loads(raw_bytes.decode("utf-8"))
assert decoded["type"] == "LETTER"
assert decoded["request_id"] == 1
assert decoded["session_id"] == "session-123"
assert decoded["payload"] == {"letter": "E"}
