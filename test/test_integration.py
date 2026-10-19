import asyncio
import pytest
from client.connection import GameClient
from protocol.message import Message
from server.server import Server


@pytest.mark.asyncio
async def test_full_game_lifecycle_real_sockets():
    """Vérifie le cycle complet d'une session : HELLO, NEW_GAME, LETTER, QUIT sur socket réelle."""
    server_instance = Server(host="127.0.0.1", port=0)
    server = await asyncio.start_server(
        server_instance.recv, server_instance.host, server_instance.port
    )
    port = server.sockets[0].getsockname()[1]

    def client_flow():
        client = GameClient(host="127.0.0.1", port=port)
        client.connect()
        try:
            # 1. HELLO -> WELCOME
            welcome = client.hello("Alice")
            assert welcome.type == "WELCOME"
            assert client.session_id is not None
            assert client.auth_token is not None
            assert welcome.payload["player_name"] == "Alice"

            # 2. NEW_GAME -> STATE
            state = client.new_game()
            assert state.type == "STATE"
            assert state.payload["status"] == "EN_COURS"
            assert state.payload["errors_left"] == 6
            assert "_" in state.payload["masked_word"]

            # 3. LETTER -> STATE
            guess_resp = client.guess("E")
            assert guess_resp.type == "STATE"
            assert "E" in guess_resp.payload["used_letters"]

            # 4. QUIT -> BYE
            quit_resp = client.quit_game()
            assert quit_resp.type == "BYE"
            assert client.session_id is None
        finally:
            client.close()

    async with server:
        await asyncio.to_thread(client_flow)


@pytest.mark.asyncio
async def test_resume_and_resilience_after_disconnect():
    """Scénario de coupure réseau : le client se déconnecte, puis reprend sa session avec RESUME."""
    server_instance = Server(host="127.0.0.1", port=0)
    server = await asyncio.start_server(
        server_instance.recv, server_instance.host, server_instance.port
    )
    port = server.sockets[0].getsockname()[1]

    def client_flow():
        # Étape 1 : Premier client lance une partie
        client1 = GameClient(host="127.0.0.1", port=port)
        client1.connect()
        client1.hello("Bob")
        client1.new_game()
        state1 = client1.guess("A")
        
        session_id = client1.session_id
        auth_token = client1.auth_token
        masked_word_before = state1.payload["masked_word"]
        used_letters_before = state1.payload["used_letters"]

        # Coupure brutale du client
        client1.close()

        # Étape 2 : Nouveau client (ou reprise) se connecte avec les tokens
        client2 = GameClient(host="127.0.0.1", port=port)
        client2.connect()
        resume_resp = client2.resume(session_id=session_id, auth_token=auth_token)

        assert resume_resp.type == "STATE"
        assert resume_resp.session_id == session_id
        assert resume_resp.payload["masked_word"] == masked_word_before
        assert resume_resp.payload["used_letters"] == used_letters_before

        client2.close()

    async with server:
        await asyncio.to_thread(client_flow)


@pytest.mark.asyncio
async def test_idempotence_replay_request():
    """Vérifie que renvoyer un même request_id retourne la même réponse en cache sans recalculer."""
    server_instance = Server(host="127.0.0.1", port=0)
    server = await asyncio.start_server(
        server_instance.recv, server_instance.host, server_instance.port
    )
    port = server.sockets[0].getsockname()[1]

    def client_flow():
        client = GameClient(host="127.0.0.1", port=port)
        client.connect()
        client.hello("Charlie")
        client.new_game()

        # Envoi d'une lettre
        resp1 = client.guess("Z")
        errors1 = resp1.payload["errors_left"]

        # Rejeu exact avec retry_last (même request_id)
        resp2 = client.retry_last()
        assert resp2.request_id == resp1.request_id
        assert resp2.payload["errors_left"] == errors1
        assert resp2.payload["masked_word"] == resp1.payload["masked_word"]

        client.close()

    async with server:
        await asyncio.to_thread(client_flow)


@pytest.mark.asyncio
async def test_ipv6_connection():
    """Vérifie la connexion en boucle locale IPv6 (::1)."""
    server_instance = Server(host=["::1", "127.0.0.1"], port=0)
    server = await asyncio.start_server(
        server_instance.recv, server_instance.host, server_instance.port
    )
    # Trouver le port IPv6
    ipv6_port = None
    for sock in server.sockets:
        addr = sock.getsockname()
        if addr[0] == "::1":
            ipv6_port = addr[1]
            break

    assert ipv6_port is not None

    def client_flow():
        client = GameClient(host="::1", port=ipv6_port)
        client.connect()
        resp = client.hello("IPv6Tester")
        assert resp.type == "WELCOME"
        client.close()

    async with server:
        await asyncio.to_thread(client_flow)
