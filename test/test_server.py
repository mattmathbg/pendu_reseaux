import asyncio
import pytest
from server.server import Server
from protocol.framing import StreamFramer
from protocol.message import Message
from core.pendu import GameState

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


async def test_new_game_during_game_in_progress_is_refused():
    srv = Server(port=0)
    session = srv.sessions.create_session("Alice")

    first, _ = await srv._dispatch_message(
        Message(type="NEW_GAME", request_id=1, session_id=session.session_id), session)
    assert first.type == "STATE"
    original_game = session.game

    second, _ = await srv._dispatch_message(
        Message(type="NEW_GAME", request_id=2, session_id=session.session_id), session)

    assert second.type == "ERROR"
    assert second.payload["code"] == "INVALID_STATE"
    assert session.game is original_game      # la partie en cours n'a pas été remplacée


async def test_new_game_after_game_finished_is_allowed():
    srv = Server(port=0)
    session = srv.sessions.create_session("Alice")

    await srv._dispatch_message(
        Message(type="NEW_GAME", request_id=1, session_id=session.session_id), session)
    session.game.state = GameState.LOST       # on force la fin de la partie

    response, _ = await srv._dispatch_message(
        Message(type="NEW_GAME", request_id=2, session_id=session.session_id), session)

    assert response.type == "STATE"
    assert session.game.state == GameState.IN_PROGRESS

async def test_quit_during_game_marks_game_abandoned():
    srv = Server(port=0)
    session = srv.sessions.create_session("Alice")
    await srv._dispatch_message(
        Message(type="NEW_GAME", request_id=1, session_id=session.session_id), session)
    game = session.game

    response, returned_session = await srv._dispatch_message(
        Message(type="QUIT", request_id=2, session_id=session.session_id), session)

    assert response.type == "BYE"
    assert response.payload["status"] == "ABANDONNE"
    assert game.state == GameState.ABANDONED
    assert returned_session is None
    assert srv.sessions.get_session(session.session_id) is None


async def test_quit_after_victory_keeps_final_state():
    srv = Server(port=0)
    session = srv.sessions.create_session("Alice")
    await srv._dispatch_message(
        Message(type="NEW_GAME", request_id=1, session_id=session.session_id), session)
    game = session.game
    game.state = GameState.WON

    response, _ = await srv._dispatch_message(
        Message(type="QUIT", request_id=2, session_id=session.session_id), session)

    assert game.state == GameState.WON    # une partie gagnée ne devient pas « abandonnée »
    assert response.payload["status"] == "GAGNE" 


async def test_quit_without_game_still_works():
    srv = Server(port=0)
    session = srv.sessions.create_session("Alice")

    response, returned_session = await srv._dispatch_message(
        Message(type="QUIT", request_id=1, session_id=session.session_id), session)

    assert response.type == "BYE"
    assert returned_session is None
    assert response.payload["status"] is None

async def test_hello_twice_on_same_connection_is_refused():
    srv = Server(port=0)
    first, session = await srv._dispatch_message(
        Message(type="HELLO", request_id=1, payload={"player_name": "Alice"}), None)
    assert first.type == "WELCOME"

    second, returned_session = await srv._dispatch_message(
        Message(type="HELLO", request_id=2, payload={"player_name": "Bob"}), session)

    assert second.type == "ERROR"
    assert second.payload["code"] == "INVALID_STATE"
    assert returned_session is session             # la connexion garde sa session
    assert len(srv.sessions.sessions) == 1         # aucune session orpheline créée


async def test_hello_after_quit_is_allowed():
    srv = Server(port=0)
    _, session = await srv._dispatch_message(
        Message(type="HELLO", request_id=1, payload={"player_name": "Alice"}), None)
    _, session = await srv._dispatch_message(
        Message(type="QUIT", request_id=2, session_id=session.session_id), session)
    assert session is None                          # QUIT détache la session

    response, new_session = await srv._dispatch_message(
        Message(type="HELLO", request_id=3, payload={"player_name": "Alice"}), None)

    assert response.type == "WELCOME"
    assert new_session is not None
    assert len(srv.sessions.sessions) == 1          # l'ancienne a été supprimée par QUIT





async def _send(writer, msg):
    writer.write(StreamFramer().frame(msg.serialize()))
    await writer.drain()


async def _read(reader):
    line = await asyncio.wait_for(reader.readline(), timeout=2)
    return Message.deserialize(line.rstrip(b"\n"))


async def test_old_connection_closing_does_not_disconnect_resumed_session():
    srv = Server(host="127.0.0.1", port=0)
    server = await asyncio.start_server(srv.recv, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    writers = []
    try:
        # connexion A : HELLO
        reader_a, writer_a = await asyncio.open_connection("127.0.0.1", port)
        writers.append(writer_a)
        await _send(writer_a, Message(type="HELLO", request_id=1,
                                      payload={"player_name": "Alice"}))
        welcome = await _read(reader_a)
        session_id = welcome.payload["session_id"]
        token = welcome.payload["auth_token"]

        # connexion B : RESUME pendant que A est encore ouverte
        reader_b, writer_b = await asyncio.open_connection("127.0.0.1", port)
        writers.append(writer_b)
        await _send(writer_b, Message(type="RESUME", request_id=1,
                                      session_id=session_id,
                                      payload={"auth_token": token}))
        assert (await _read(reader_b)).type == "STATE"

        # l'ancienne connexion A se ferme enfin
        writer_a.close()
        await asyncio.sleep(0.2)   # laisse le serveur traiter la fermeture de A

        assert srv.sessions.sessions[session_id].is_connected is True
    finally:
        for w in writers:
            w.close()
        server.close()
        await server.wait_closed()


async def test_closing_the_only_connection_disconnects_session():
    srv = Server(host="127.0.0.1", port=0)
    server = await asyncio.start_server(srv.recv, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    writers = []
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writers.append(writer)
        await _send(writer, Message(type="HELLO", request_id=1,
                                    payload={"player_name": "Alice"}))
        session_id = (await _read(reader)).payload["session_id"]

        writer.close()
        await asyncio.sleep(0.2)

        assert srv.sessions.sessions[session_id].is_connected is False
    finally:
        for w in writers:
            w.close()
        server.close()
        await server.wait_closed()

async def _connect_and_start(port, writers):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writers.append(writer)
    await _send(writer, Message(type="HELLO", request_id=1,
                                payload={"player_name": "Alice"}))
    session_id = (await _read(reader)).payload["session_id"]
    await _send(writer, Message(type="NEW_GAME", request_id=2, session_id=session_id))
    await _read(reader)
    return reader, writer, session_id


async def test_handler_crash_returns_error_and_keeps_connection_alive():
    srv = Server(host="127.0.0.1", port=0)

    async def boom(msg, session):
        raise RuntimeError("detail interne")

    srv.dispatcher._handlers["LETTER"] = boom      # ce handler va planter

    server = await asyncio.start_server(srv.recv, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    writers = []
    try:
        reader, writer, sid = await _connect_and_start(port, writers)

        await _send(writer, Message(type="LETTER", request_id=3, session_id=sid,
                                    payload={"letter": "e"}))
        error = await _read(reader)
        assert error.type == "ERROR"
        assert error.request_id == 3
        assert error.payload["code"] == "INTERNAL_ERROR"
        assert "detail interne" not in error.payload["message"]   # rien n'est divulgué

        # la connexion fonctionne toujours
        await _send(writer, Message(type="QUIT", request_id=4, session_id=sid))
        assert (await _read(reader)).type == "BYE"
    finally:
        for w in writers:
            w.close()
        server.close()
        await server.wait_closed()


async def test_normal_application_error_is_not_internal_error():
    srv = Server(host="127.0.0.1", port=0)
    server = await asyncio.start_server(srv.recv, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    writers = []
    try:
        reader, writer, sid = await _connect_and_start(port, writers)

        await _send(writer, Message(type="LETTER", request_id=3, session_id=sid,
                                    payload={"letter": "1"}))   # lettre invalide
        error = await _read(reader)
        assert error.type == "ERROR"
        assert error.payload["code"] != "INTERNAL_ERROR"
    finally:
        for w in writers:
            w.close()
        server.close()
        await server.wait_closed()