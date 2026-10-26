import socket
import threading
import pytest
from client.connection import GameClient
from protocol.framing import StreamFramer
from protocol.message import Message


# --- OUTILS DE TEST ---

class FakeSocket:
    """Fausse socket : enregistre les envois et rejoue des réponses préparées."""
    def __init__(self, chunks=()):
        self.sent = []                # tout ce que le client a envoyé
        self.chunks = list(chunks)    # ce que recv() va renvoyer, dans l'ordre
        self.closed = False

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, size):
        if self.chunks:
            chunk = self.chunks.pop(0)
            if isinstance(chunk, Exception):
                raise chunk           # permet de simuler un timeout
            return chunk
        return b""                    # plus rien : le serveur a fermé

    def close(self):
        self.closed = True


def server_reply(request_id, msg_type="STATE", **payload):
    """Fabrique les octets qu'enverrait le serveur (message + \n)."""
    msg = Message(type=msg_type, request_id=request_id, payload=payload)
    return StreamFramer().frame(msg.serialize())


def make_client(*chunks):
    """Client déjà « connecté » à une fausse socket."""
    client = GameClient()
    client.sock = FakeSocket(chunks)
    return client


def sent_message(client, index=0) -> Message:
    """Relit le message que le client a envoyé (le n-ième)."""
    return Message.deserialize(client.sock.sent[index].rstrip(b"\n"))


# --- TESTS : ÉTAT INITIAL, CONNEXION, FERMETURE ---

def test_initial_state():
    client = GameClient()
    assert client.sock is None
    assert client.next_request_id == 1
    assert client.session_id is None
    assert client.last_message is None


def test_connect_uses_host_and_port(monkeypatch):
    calls = []

    def fake_create_connection(address, timeout):
        calls.append((address, timeout))
        return FakeSocket()

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    client = GameClient("::1", 9999)
    client.connect()
    assert calls == [(("::1", 9999), 5)]
    assert client.sock is not None


def test_connect_resets_framer(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", lambda address, timeout: FakeSocket())
    client = GameClient()
    client.framer.feed(b"restes d'une ancienne connexion")
    client.connect()
    assert client.framer.get_next_message() is None
    assert len(client.framer.buffer) == 0


def test_close_closes_socket_and_resets():
    client = make_client()
    fake = client.sock
    client.close()
    assert fake.closed is True
    assert client.sock is None


def test_close_without_connection_does_nothing():
    client = GameClient()
    client.close()   # ne doit pas lever d'erreur
    assert client.sock is None


# --- TESTS : ENVOI D'UNE REQUÊTE ---

def test_request_sends_framed_message():
    client = make_client(server_reply(1))
    client.request("NEW_GAME")
    data = client.sock.sent[0]
    assert data.endswith(b"\n")
    assert data.count(b"\n") == 1


def test_request_sends_correct_fields():
    client = make_client(server_reply(1))
    client.request("LETTER", {"letter": "e"})
    msg = sent_message(client)
    assert msg.type == "LETTER"
    assert msg.request_id == 1
    assert msg.session_id is None
    assert msg.payload == {"letter": "e"}


def test_request_without_payload_sends_empty_payload():
    client = make_client(server_reply(1))
    client.request("NEW_GAME")
    assert sent_message(client).payload == {}


def test_request_id_increments_on_each_new_request():
    client = make_client(server_reply(1), server_reply(2), server_reply(3))
    client.request("NEW_GAME")
    client.request("LETTER", {"letter": "a"})
    client.request("LETTER", {"letter": "b"})
    ids = [sent_message(client, i).request_id for i in range(3)]
    assert ids == [1, 2, 3]
    assert client.next_request_id == 4


def test_request_includes_session_id_when_known():
    client = make_client(server_reply(1))
    client.session_id = "S42"
    client.request("LETTER", {"letter": "e"})
    assert sent_message(client).session_id == "S42"


def test_request_returns_server_response():
    client = make_client(server_reply(1, word="_e__e", remaining=4))
    response = client.request("LETTER", {"letter": "e"})
    assert response.type == "STATE"
    assert response.request_id == 1
    assert response.payload == {"word": "_e__e", "remaining": 4}


# --- TESTS : LECTURE DU FLUX TCP (FRAMING CÔTÉ CLIENT) ---

def test_response_split_in_two_chunks():
    data = server_reply(1, word="_e__e")
    client = make_client(data[:10], data[10:])
    response = client.request("NEW_GAME")
    assert response.request_id == 1
    assert response.payload == {"word": "_e__e"}


def test_response_received_one_byte_at_a_time():
    data = server_reply(1, word="abc")
    client = make_client(*[data[i:i + 1] for i in range(len(data))])
    response = client.request("NEW_GAME")
    assert response.payload == {"word": "abc"}


def test_two_messages_in_one_chunk_are_read_one_after_the_other():
    client = make_client(server_reply(1) + server_reply(2))
    assert client._read_message().request_id == 1
    assert client._read_message().request_id == 2   # déjà dans le framer, pas de recv


# --- TESTS : ERREURS DE TRANSPORT ---

def test_server_closing_connection_raises_connection_error():
    client = make_client()   # recv() renverra b"" tout de suite
    with pytest.raises(ConnectionError):
        client.request("NEW_GAME")


def test_connection_closed_in_the_middle_of_a_message():
    data = server_reply(1)
    client = make_client(data[:10])   # message coupé, puis plus rien
    with pytest.raises(ConnectionError):
        client.request("NEW_GAME")


def test_timeout_is_propagated():
    client = make_client(socket.timeout())
    with pytest.raises(socket.timeout):
        client.request("NEW_GAME")


# --- TESTS : RENVOI D'UNE REQUÊTE (partie 6.1 du sujet) ---

def test_request_keeps_last_message():
    client = make_client(server_reply(1))
    client.request("LETTER", {"letter": "e"})
    assert client.last_message.type == "LETTER"
    assert client.last_message.request_id == 1


def test_retry_last_resends_same_request_id():
    client = make_client(server_reply(5), server_reply(5))
    client.next_request_id = 5
    client.request("LETTER", {"letter": "e"})
    client.retry_last()
    first, second = sent_message(client, 0), sent_message(client, 1)
    assert first.request_id == second.request_id == 5
    assert first.payload == second.payload == {"letter": "e"}


def test_retry_last_does_not_increment_counter():
    client = make_client(server_reply(1), server_reply(1))
    client.request("NEW_GAME")
    counter_before = client.next_request_id
    client.retry_last()
    assert client.next_request_id == counter_before


def test_retry_after_lost_response():
    """Scénario du sujet : la réponse se perd, on renvoie avec le même id."""
    client = make_client()                       # 1re tentative : connexion coupée
    with pytest.raises(ConnectionError):
        client.request("LETTER", {"letter": "e"})
    client.sock = FakeSocket([server_reply(1, word="_e__e")])   # « reconnexion »
    response = client.retry_last()
    assert response.request_id == 1
    assert sent_message(client).request_id == 1   # même numéro que la 1re tentative


# --- TEST AVEC UN VRAI RÉSEAU ---

def test_real_socket_roundtrip():
    """Mini-serveur dans un thread : vérifie que tout marche avec une vraie socket TCP."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))   # port 0 : l'OS choisit un port libre
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve():
        conn, _ = listener.accept()
        framer = StreamFramer()
        raw = None
        while raw is None:
            framer.feed(conn.recv(4096))
            raw = framer.get_next_message()
        request = Message.deserialize(raw)
        conn.sendall(server_reply(request.request_id, status="OK"))
        conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    client = GameClient("127.0.0.1", port)
    client.connect()
    try:
        response = client.request("NEW_GAME")
        assert response.request_id == 1
        assert response.payload == {"status": "OK"}
    finally:
        client.close()
        listener.close()
        thread.join(timeout=2)


def test_auto_reconnect_replays_original_request(monkeypatch):
    client = make_client()   # 1re socket : recv() renvoie b"" = coupure
    client.session_id, client.auth_token, client.auto_reconnect = "S1", "tok", True

    def fake_connect():
        client.framer = StreamFramer()
        client.sock = FakeSocket([server_reply(2, status="EN_COURS"),
                                  server_reply(1, masked_word="_ E _")])

    monkeypatch.setattr(client, "connect", fake_connect)

    response = client.request("LETTER", {"letter": "e"})   # request_id 1

    sent = [Message.deserialize(d.rstrip(b"\n")) for d in client.sock.sent]
    assert [m.type for m in sent] == ["RESUME", "LETTER"]
    assert sent[1].request_id == 1                          # même id qu'au départ
    assert response.request_id == 1


def test_send_without_socket_does_not_reconnect_silently(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("connect() ne doit pas être appelé ici")

    monkeypatch.setattr(socket, "create_connection", boom)
    client = GameClient()          # jamais connecté
    with pytest.raises(ConnectionError):
        client._send_and_wait(Message("NEW_GAME", 1))
