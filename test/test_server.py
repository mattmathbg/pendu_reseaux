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


async def test_letter_timeout_marks_game_lost_and_allows_new_game():
    srv = Server(port=0, move_timeout=0.01)
    session = srv.sessions.create_session("Alice", move_timeout=0.01)
    # 1. Démarrer une nouvelle partie
    resp1, _ = await srv._dispatch_message(
        Message(type="NEW_GAME", request_id=1, session_id=session.session_id), session
    )
    assert resp1.type == "STATE"
    assert session.game.state == GameState.IN_PROGRESS

    # 2. Attendre que le timeout de coup expire
    await asyncio.sleep(0.02)
    assert session.is_timed_out() is True

    # 3. Proposer une lettre doit renvoyer TIMEOUT et marquer la partie comme LOST
    resp2, _ = await srv._dispatch_message(
        Message(type="LETTER", request_id=2, session_id=session.session_id, payload={"letter": "E"}), session
    )
    assert resp2.type == "ERROR"
    assert resp2.payload["code"] == "TIMEOUT"
    assert resp2.payload["status"] == "PERDU"
    assert resp2.payload["secret_word"] == session.game.secret_word
    assert session.game.state == GameState.LOST
    assert session.game.is_finished() is True

    # 4. Le joueur peut alors démarrer une NOUVELLE partie sans deadlock
    resp3, _ = await srv._dispatch_message(
        Message(type="NEW_GAME", request_id=3, session_id=session.session_id), session
    )
    assert resp3.type == "STATE"
    assert session.game.state == GameState.IN_PROGRESS


async def test_new_game_in_progress_does_not_call_api_or_overwrite_theme(monkeypatch):
    srv = Server(port=0)
    session = srv.sessions.create_session("Alice")
    session.game = Pendu("PYTHON")
    session.theme = "Animaux"

    called = []
    monkeypatch.setattr("server.server.get_word_from_api", lambda *a, **k: called.append(a) or ("AUTRE", "Sports"))

    resp, _ = await srv._dispatch_message(
        Message(type="NEW_GAME", request_id=2, session_id=session.session_id, payload={"category_id": 16}),
        session,
    )
    assert resp.type == "ERROR"
    assert resp.payload["code"] == "INVALID_STATE"
    assert called == []
    assert session.theme == "Animaux"




async def _duel_player(srv, name):
    session, writer = _player(srv, name)
    return session, writer


async def _join_duel(srv, session, duel_id):
    response, _ = await srv._dispatch_message(
        Message(type="JOIN_DUEL", request_id=2, session_id=session.session_id,
                payload={"duel_id": duel_id}), session)
    return response


async def _create_duel(srv, session, duel_id=None):
    response, _ = await srv._dispatch_message(
        Message(type="CREATE_DUEL", request_id=1, session_id=session.session_id,
                payload={"duel_id": duel_id} if duel_id is not None else {}), session)
    assert response.type == "DUEL"
    return response.payload["duel_id"]


async def test_create_duel_waits_for_second_player():
    srv = Server(port=0)
    alice, _ = await _duel_player(srv, "Alice")
    response, _ = await srv._dispatch_message(
        Message(type="CREATE_DUEL", request_id=1, session_id=alice.session_id), alice)
    assert response.type == "DUEL"
    assert response.payload["status"] == "EN_ATTENTE"
    assert response.payload["players"] == ["Alice"]


async def test_create_duel_uses_custom_letter_code():
    srv = Server(port=0)
    alice, _ = await _duel_player(srv, "Alice")
    bob, _ = await _duel_player(srv, "Bob")

    duel_id = await _create_duel(srv, alice, "amis")
    response = await _join_duel(srv, bob, "amis")

    assert duel_id == "AMIS"
    assert response.type == "DUEL"
    assert response.payload["status"] == "EN_COURS"


async def test_create_duel_rejects_duplicate_custom_code():
    srv = Server(port=0)
    alice, _ = await _duel_player(srv, "Alice")
    bob, _ = await _duel_player(srv, "Bob")
    await _create_duel(srv, alice, "AMIS")

    response, _ = await srv._dispatch_message(
        Message(type="CREATE_DUEL", request_id=2, session_id=bob.session_id,
                payload={"duel_id": "amis"}), bob)

    assert response.type == "ERROR"
    assert response.payload["code"] == "DUEL_EXISTS"


async def test_join_starts_duel_and_gives_first_turn_to_creator():
    srv = Server(port=0)
    alice, alice_w = await _duel_player(srv, "Alice")
    bob, _ = await _duel_player(srv, "Bob")
    duel_id = await _create_duel(srv, alice)

    response = await _join_duel(srv, bob, duel_id)

    assert response.payload["status"] == "EN_COURS"
    assert response.payload["players"] == ["Alice", "Bob"]
    assert response.payload["turn"] == "Alice"
    pushed = alice_w.messages()
    assert len(pushed) == 1
    assert pushed[0].type == "DUEL_STATE"
    assert pushed[0].payload["status"] == "EN_COURS"
    assert pushed[0].payload["turn"] == "Alice"


async def test_third_player_is_refused():
    srv = Server(port=0)
    alice, _ = await _duel_player(srv, "Alice")
    bob, _ = await _duel_player(srv, "Bob")
    carol, _ = await _duel_player(srv, "Carol")
    duel_id = await _create_duel(srv, alice)
    await _join_duel(srv, bob, duel_id)

    response = await _join_duel(srv, carol, duel_id)

    assert response.type == "ERROR"
    assert response.payload["code"] == "INVALID_STATE"


async def test_letter_out_of_turn_is_refused():
    srv = Server(port=0)
    alice, _ = await _duel_player(srv, "Alice")
    bob, bob_w = await _duel_player(srv, "Bob")
    duel_id = await _create_duel(srv, alice)
    await _join_duel(srv, bob, duel_id)

    response, _ = await srv._dispatch_message(
        Message(type="LETTER", request_id=3, session_id=bob.session_id,
                payload={"letter": "p"}), bob)

    assert response.payload["code"] == "NOT_YOUR_TURN"


async def test_turn_alternates_and_state_is_pushed_to_other_player():
    srv = Server(port=0)
    alice, alice_w = await _duel_player(srv, "Alice")
    bob, bob_w = await _duel_player(srv, "Bob")
    duel_id = await _create_duel(srv, alice)
    await _join_duel(srv, bob, duel_id)

    response, _ = await srv._dispatch_message(
        Message(type="LETTER", request_id=3, session_id=alice.session_id,
                payload={"letter": "p"}), alice)

    assert response.payload["turn"] == "Bob"
    pushed = bob_w.messages()
    assert len(pushed) == 1
    assert pushed[0].type == "DUEL_STATE"
    assert pushed[0].request_id == 0
    creator_messages = alice_w.messages()
    assert len(creator_messages) == 1
    assert creator_messages[0].type == "DUEL_STATE"
    assert creator_messages[0].payload["status"] == "EN_COURS"


async def test_player_who_finds_last_letter_wins(monkeypatch):
    monkeypatch.setattr("server.server.get_word_from_api", lambda *a: ("PYTHON", "Test"))
    srv = Server(port=0)
    alice, alice_w = await _duel_player(srv, "Alice")
    bob, bob_w = await _duel_player(srv, "Bob")
    duel_id = await _create_duel(srv, alice)
    await _join_duel(srv, bob, duel_id)
    # Ordre de tour : Alice, Bob, Alice... ; Alice trouve la dernière lettre
    sequence = [(alice, "p"), (bob, "x"), (alice, "y"), (bob, "z"),
                (alice, "t"), (bob, "q"), (alice, "h"), (bob, "w"), (alice, "o"), (bob, "k"), (alice, "n")]
    for i, (player, letter) in enumerate(sequence):
        await srv._dispatch_message(
            Message(type="LETTER", request_id=3 + i, session_id=player.session_id,
                    payload={"letter": letter}), player)

    end_msgs = [m for m in bob_w.messages() if m.type == "DUEL_END"]
    assert end_msgs[0].payload["winner"] == "Alice"


async def test_disconnected_player_forfeits_after_60_seconds():
    srv = Server(port=0)
    alice, alice_w = await _duel_player(srv, "Alice")
    bob, bob_w = await _duel_player(srv, "Bob")
    duel_id = await _create_duel(srv, alice)
    await _join_duel(srv, bob, duel_id)

    bob.handle_disconnect()
    await srv.check_duel_forfeits(now=bob.disconnect_timestamp + 61)

    end_msgs = [m for m in alice_w.messages() if m.type == "DUEL_END"]
    assert end_msgs[0].payload["winner"] == "Alice"
    assert end_msgs[0].payload["reason"] == "forfait"
    assert duel_id not in srv.duels
    assert alice.duel is None
    assert bob.duel is None


async def test_disconnect_timer_forfeits_after_grace_period(monkeypatch):
    srv = Server(port=0)
    alice, alice_w = await _duel_player(srv, "Alice")
    bob, _ = await _duel_player(srv, "Bob")
    duel_id = await _create_duel(srv, alice)
    await _join_duel(srv, bob, duel_id)
    bob.handle_disconnect()
    disconnected_at = bob.disconnect_timestamp

    async def skip_delay(_seconds):
        pass

    monkeypatch.setattr("server.server.asyncio.sleep", skip_delay)
    monkeypatch.setattr("server.server.time", lambda: disconnected_at + 61)

    await srv._forfeit_after_disconnect(srv.duels[duel_id], bob, disconnected_at)

    end_msgs = [message for message in alice_w.messages() if message.type == "DUEL_END"]
    assert end_msgs[0].payload["winner"] == "Alice"
    assert end_msgs[0].payload["reason"] == "forfait"
    assert duel_id not in srv.duels


async def test_disconnect_timer_does_not_forfeit_resumed_player(monkeypatch):
    srv = Server(port=0)
    alice, alice_w = await _duel_player(srv, "Alice")
    bob, _ = await _duel_player(srv, "Bob")
    duel_id = await _create_duel(srv, alice)
    await _join_duel(srv, bob, duel_id)
    bob.handle_disconnect()
    disconnected_at = bob.disconnect_timestamp

    async def resume_during_delay(_seconds):
        bob.reconnect(bob.auth_token)

    monkeypatch.setattr("server.server.asyncio.sleep", resume_during_delay)
    monkeypatch.setattr("server.server.time", lambda: disconnected_at + 61)

    await srv._forfeit_after_disconnect(srv.duels[duel_id], bob, disconnected_at)

    assert srv.duels[duel_id].status == "EN_COURS"
    assert not [message for message in alice_w.messages() if message.type == "DUEL_END"]


async def test_cleanup_loop_awaits_duel_forfeit_check(monkeypatch):
    srv = Server(port=0)
    checks = []
    sleep_calls = 0

    async def check_forfeits():
        checks.append(True)

    async def stop_loop(_delay):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(srv, "check_duel_forfeits", check_forfeits)
    monkeypatch.setattr("server.server.asyncio.sleep", stop_loop)

    with pytest.raises(asyncio.CancelledError):
        await srv._cleanup_loop()

    assert checks == [True]


async def test_disconnected_player_who_returns_in_time_keeps_duel():
    srv = Server(port=0)
    alice, alice_w = await _duel_player(srv, "Alice")
    bob, _ = await _duel_player(srv, "Bob")
    duel_id = await _create_duel(srv, alice)
    await _join_duel(srv, bob, duel_id)

    bob.handle_disconnect()
    await srv.check_duel_forfeits(now=bob.disconnect_timestamp + 30)

    creator_messages = alice_w.messages()
    assert len(creator_messages) == 1
    assert creator_messages[0].type == "DUEL_STATE"
    assert srv.duels[duel_id].status == "EN_COURS"
