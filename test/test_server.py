import asyncio
import pytest
from server.server import Server
from protocol.framing import StreamFramer
from protocol.message import Message
from core.pendu import GameState , Pendu
MAX_MESSAGE_SIZE = 8192

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

async def _session_with_game(srv):
    """Session avec une partie dont le mot est connu : PYTHON."""
    session = srv.sessions.create_session("Alice")
    await srv._dispatch_message(
        Message(type="NEW_GAME", request_id=1, session_id=session.session_id), session)
    session.game = Pendu("PYTHON")
    return session


async def test_message_without_session_returns_unknown_session():
    srv = Server(port=0)
    response, _ = await srv._dispatch_message(
        Message(type="LETTER", request_id=1, payload={"letter": "e"}), None)
    assert response.payload["code"] == "UNKNOWN_SESSION"


async def test_resume_unknown_session_returns_unknown_session():
    srv = Server(port=0)
    response, returned = await srv._dispatch_message(
        Message(type="RESUME", request_id=1, session_id="inconnue",
                payload={"auth_token": "x"}), None)
    assert response.payload["code"] == "UNKNOWN_SESSION"
    assert returned is None


async def test_resume_with_wrong_token_returns_player_not_allowed():
    srv = Server(port=0)
    session = srv.sessions.create_session("Alice")
    response, returned = await srv._dispatch_message(
        Message(type="RESUME", request_id=1, session_id=session.session_id,
                payload={"auth_token": "faux"}), None)
    assert response.payload["code"] == "PLAYER_NOT_ALLOWED"
    assert returned is None


async def test_resume_without_session_id_returns_invalid_message():
    srv = Server(port=0)
    response, _ = await srv._dispatch_message(
        Message(type="RESUME", request_id=1, payload={"auth_token": "x"}), None)
    assert response.payload["code"] == "INVALID_MESSAGE"


async def test_unknown_message_type_returns_invalid_message():
    srv = Server(port=0)
    session = srv.sessions.create_session("Alice")
    response, _ = await srv._dispatch_message(
        Message(type="DANCE", request_id=1, session_id=session.session_id), session)
    assert response.payload["code"] == "INVALID_MESSAGE"


async def test_letter_without_game_returns_invalid_state():
    srv = Server(port=0)
    session = srv.sessions.create_session("Alice")
    response, _ = await srv._dispatch_message(
        Message(type="LETTER", request_id=1, session_id=session.session_id,
                payload={"letter": "a"}), session)
    assert response.payload["code"] == "INVALID_STATE"


async def test_invalid_letter_returns_invalid_letter():
    srv = Server(port=0)
    session = await _session_with_game(srv)
    response, _ = await srv._dispatch_message(
        Message(type="LETTER", request_id=2, session_id=session.session_id,
                payload={"letter": "12"}), session)
    assert response.payload["code"] == "INVALID_LETTER"


async def test_letter_already_tried_returns_invalid_letter():
    srv = Server(port=0)
    session = await _session_with_game(srv)
    sid = session.session_id
    await srv._dispatch_message(
        Message(type="LETTER", request_id=2, session_id=sid, payload={"letter": "p"}), session)
    response, _ = await srv._dispatch_message(
        Message(type="LETTER", request_id=3, session_id=sid, payload={"letter": "p"}), session)
    assert response.payload["code"] == "INVALID_LETTER"


async def test_letter_after_game_finished_returns_invalid_state():
    srv = Server(port=0)
    session = await _session_with_game(srv)
    session.game.state = GameState.LOST
    response, _ = await srv._dispatch_message(
        Message(type="LETTER", request_id=2, session_id=session.session_id,
                payload={"letter": "a"}), session)
    assert response.payload["code"] == "INVALID_STATE"


async def test_malformed_message_returns_invalid_message():
    srv = Server(host="127.0.0.1", port=0)
    server = await asyncio.start_server(srv.recv, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    writers = []
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writers.append(writer)
        writer.write(b"pas du json\n")
        await writer.drain()
        error = await _read(reader)
        assert error.type == "ERROR"
        assert error.payload["code"] == "INVALID_MESSAGE"
    finally:
        for w in writers:
            w.close()
        server.close()
        await server.wait_closed()

async def test_state_contains_max_errors():
    srv = Server(port=0)
    session = srv.sessions.create_session("Alice")
    response, _ = await srv._dispatch_message(
        Message(type="NEW_GAME", request_id=1, session_id=session.session_id), session)
    assert response.payload["max_errors"] == session.game.max_errors
    assert response.payload["errors_left"] == response.payload["max_errors"]


async def test_max_errors_stays_constant_after_wrong_letter():
    srv = Server(port=0)
    session = await _session_with_game(srv)
    response, _ = await srv._dispatch_message(
        Message(type="LETTER", request_id=2, session_id=session.session_id,
                payload={"letter": "z"}), session)    # Z n'est pas dans PYTHON
    assert response.payload["max_errors"] == 6        # le total ne bouge pas
    assert response.payload["errors_left"] == 5       # seul le restant diminue


async def test_oversized_message_returns_error_and_closes_connection():
    srv = Server(host="127.0.0.1", port=0)
    server = await asyncio.start_server(srv.recv, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    writers = []
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writers.append(writer)
        writer.write(b"a" * (MAX_MESSAGE_SIZE + 1000))     # pas de \n
        await writer.drain()

        error = await _read(reader)
        assert error.type == "ERROR"
        assert error.payload["code"] == "INVALID_MESSAGE"

        # le serveur a fermé la connexion
        assert await asyncio.wait_for(reader.read(), timeout=2) == b""
    finally:
        for w in writers:
            w.close()
        server.close()
        await server.wait_closed()

class FakeWriter:
    """Faux writer : enregistre ce qu'on lui envoie, sans réseau."""
    def __init__(self):
        self.data = b""

    def write(self, data):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass

    def messages(self):
        return [Message.deserialize(line) for line in self.data.split(b"\n") if line]


class BrokenWriter(FakeWriter):
    """Faux writer dont la connexion est morte : write lève une erreur."""
    def write(self, data):
        raise ConnectionResetError("connexion morte")
    

def _player(srv, name):
    session = srv.sessions.create_session(name)
    writer = FakeWriter()
    session.owner = writer
    return session, writer


async def _join(srv, session, room):
    response, _ = await srv._dispatch_message(
        Message(type="JOIN_ROOM", request_id=1, session_id=session.session_id,
                payload={"room": room}), session)
    assert response.type == "ROOM"


async def test_global_chat_reaches_everyone_but_sender():
    srv = Server(port=0)
    alice, alice_w = _player(srv, "Alice")
    _, bob_w = _player(srv, "Bob")
    _, carol_w = _player(srv, "Carol")

    response, _ = await srv._dispatch_message(
        Message(type="CHAT", request_id=1, session_id=alice.session_id,
                payload={"text": "salut", "scope": "global"}), alice)

    for w in (bob_w, carol_w):
        pushed = w.messages()
        assert len(pushed) == 1
        assert pushed[0].request_id == 0
        assert pushed[0].payload["player"] == "Alice"
        assert pushed[0].payload["text"] == "salut"
    assert alice_w.data == b""          # l'expéditeur ne reçoit pas son propre push
    assert response.type == "CHAT"
    assert response.request_id == 1     # sa réponse porte son numéro


async def test_room_chat_only_reaches_same_room():
    srv = Server(port=0)
    alice, _ = _player(srv, "Alice")
    bob, bob_w = _player(srv, "Bob")
    carol, carol_w = _player(srv, "Carol")
    await _join(srv, alice, "salon1")
    await _join(srv, bob, "salon1")
    await _join(srv, carol, "salon2")

    response, _ = await srv._dispatch_message(
        Message(type="CHAT", request_id=2, session_id=alice.session_id,
                payload={"text": "salut", "scope": "room"}), alice)

    assert len(bob_w.messages()) == 1   # même salon
    assert carol_w.data == b""          # autre salon : exclu par le filtre
    assert response.payload["room_id"] == "salon1"

async def test_offline_player_receives_nothing_and_others_still_do():
    srv = Server(port=0)
    alice, _ = _player(srv, "Alice")
    _, bob_w = _player(srv, "Bob")
    offline, offline_w = _player(srv, "Offline")
    offline.handle_disconnect()

    await srv._dispatch_message(
        Message(type="CHAT", request_id=1, session_id=alice.session_id,
                payload={"text": "salut", "scope": "global"}), alice)

    assert offline_w.data == b""
    assert len(bob_w.messages()) == 1


async def test_dead_connection_does_not_block_others():
    srv = Server(port=0)
    alice, _ = _player(srv, "Alice")
    dead = srv.sessions.create_session("Dead")
    dead.owner = BrokenWriter()
    dead.is_connected = True
    _, carol_w = _player(srv, "Carol")

    response, _ = await srv._dispatch_message(
        Message(type="CHAT", request_id=1, session_id=alice.session_id,
                payload={"text": "salut", "scope": "global"}), alice)

    assert response.type == "CHAT"
    assert len(carol_w.messages()) == 1


async def test_room_chat_without_room_is_refused_and_sends_nothing():
    srv = Server(port=0)
    alice, _ = _player(srv, "Alice")
    _, bob_w = _player(srv, "Bob")

    response, _ = await srv._dispatch_message(
        Message(type="CHAT", request_id=1, session_id=alice.session_id,
                payload={"text": "salut", "scope": "room"}), alice)

    assert response.payload["code"] == "INVALID_STATE"
    assert bob_w.data == b""


async def test_invalid_text_is_refused_and_sends_nothing():
    srv = Server(port=0)
    alice, _ = _player(srv, "Alice")
    _, bob_w = _player(srv, "Bob")

    for bad in ["", "   ", "x" * 201, 42]:
        response, _ = await srv._dispatch_message(
            Message(type="CHAT", request_id=1, session_id=alice.session_id,
                    payload={"text": bad, "scope": "global"}), alice)
        assert response.payload["code"] == "INVALID_MESSAGE"

    assert bob_w.data == b""


async def test_sender_gets_own_request_id_not_zero():
    srv = Server(port=0)
    alice, _ = _player(srv, "Alice")
    _player(srv, "Bob")

    response, _ = await srv._dispatch_message(
        Message(type="CHAT", request_id=7, session_id=alice.session_id,
                payload={"text": "salut", "scope": "global"}), alice)

    assert response.request_id == 7