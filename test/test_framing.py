import pytest
from protocol.framing import StreamFramer

@pytest.fixture
def framer() -> StreamFramer:
    return StreamFramer()

def test_single_complete_message(framer: StreamFramer):
    framer.feed(b"HELLO\n")
    assert framer.get_next_message() == b"HELLO"
    assert framer.get_next_message() is None

def test_fragmented_message(framer: StreamFramer):
    # Simule un message découpé par le transport TCP
    framer.feed(b"HEL")
    assert framer.get_next_message() is None  # Message incomplet
    
    framer.feed(b"LO\n")
    assert framer.get_next_message() == b"HELLO"
    assert framer.get_next_message() is None

def test_glued_messages(framer: StreamFramer):
    # Simule deux messages reçus dans un seul recv() TCP
    framer.feed(b"MSG1\nMSG2\n")
    assert framer.get_next_message() == b"MSG1"
    assert framer.get_next_message() == b"MSG2"
    assert framer.get_next_message() is None

def test_frame_adds_delimiter(framer: StreamFramer):
    assert framer.frame(b"DATA") == b"DATA\n"