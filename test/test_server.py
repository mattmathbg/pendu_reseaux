import asyncio
import pytest
from server.server import Server
from protocol.framing import StreamFramer
from protocol.message import Message

@pytest.mark.asyncio
async def test_server_hello_then_new_game():
    server_instance = Server(host="127.0.0.1", port=0)
    server = await asyncio.start_server(
        server_instance.recv, server_instance.host, server_instance.port
    )
    addr = server.sockets[0].getsockname()
    host, port = addr[0], addr[1]

    async with server:
        reader, writer = await asyncio.open_connection(host, port)
        framer = StreamFramer()

        # 1. Envoi HELLO
        hello_msg = Message(type="HELLO", request_id=1, payload={"player_name": "Testeur"})
        writer.write(framer.frame(hello_msg.serialize()))
        await writer.drain()

        # Réception WELCOME
        chunk = await reader.read(4096)
        framer.feed(chunk)
        welcome = Message.deserialize(framer.get_next_message())
        assert welcome.type == "WELCOME"
        session_id = welcome.session_id
        assert session_id is not None

        # 2. Envoi NEW_GAME
        new_game_msg = Message(type="NEW_GAME", request_id=2, session_id=session_id)
        writer.write(framer.frame(new_game_msg.serialize()))
        await writer.drain()

        # Réception STATE
        chunk = await reader.read(4096)
        framer.feed(chunk)
        state = Message.deserialize(framer.get_next_message())
        assert state.type == "STATE"
        assert state.payload["status"] == "EN_COURS"
        assert "_" in state.payload["masked_word"]

        writer.close()
        await writer.wait_closed()

async def test_letter_with_session_id_but_no_resume_is_refused():
        srv = Server(port=0)
        session = srv.sessions.create_session("Alice")
        msg = Message(type="LETTER", request_id=1,
                    session_id=session.session_id, payload={"letter": "e"})

        response, returned_session = await srv._dispatch_message(msg, None)

        assert response.type == "ERROR"
        assert returned_session is None