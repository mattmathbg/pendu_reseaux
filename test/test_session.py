from types import SimpleNamespace
import uuid
import pytest
import core.session as session_module
from core.session import GameSession, SessionManager


def set_time(monkeypatch, value):
    monkeypatch.setattr(session_module, "time", SimpleNamespace(time=lambda: value))


# --- TESTS POUR GAME SESSION ---

def test_initial_state():
    session = GameSession("Alice")
    assert session.player_name == "Alice"
    assert session.game is None
    assert session.is_connected is True
    assert session.disconnect_timestamp is None
    assert str(uuid.UUID(session.session_id)) == session.session_id
    assert str(uuid.UUID(session.auth_token)) == session.auth_token


def test_handle_disconnect_records_time(monkeypatch):
    set_time(monkeypatch, 123.5)
    session = GameSession("Alice")
    session.handle_disconnect()
    assert session.is_connected is False
    assert session.disconnect_timestamp == 123.5


def test_reconnect_with_valid_token_restores_session(monkeypatch):
    set_time(monkeypatch, 10)
    session = GameSession("Alice")
    session.handle_disconnect()
    assert session.reconnect(session.auth_token) is True
    assert session.is_connected is True
    assert session.disconnect_timestamp is None


def test_reconnect_with_invalid_token_does_not_change_state(monkeypatch):
    set_time(monkeypatch, 10)
    session = GameSession("Alice")
    session.handle_disconnect()
    disconnected_at = session.disconnect_timestamp
    assert session.reconnect("wrong-token") is False
    assert session.is_connected is False
    assert session.disconnect_timestamp == disconnected_at


def test_cached_response_is_returned_only_for_matching_request_id():
    session = GameSession("Alice")
    response = {"status": "ok"}
    session.save_response(7, response)
    assert session.get_cached_response(7) == response
    assert session.get_cached_response(8) is None


def test_connected_session_is_not_expired():
    assert GameSession("Alice").is_expired() is False


def test_disconnected_session_expiration_boundary(monkeypatch):
    set_time(monkeypatch, 100)
    session = GameSession("Alice")
    session.handle_disconnect()
    set_time(monkeypatch, 160)
    assert session.is_expired(timeout=60) is False
    set_time(monkeypatch, 160.01)
    assert session.is_expired(timeout=60) is True


# --- TESTS POUR SESSION MANAGER ---

def test_session_manager_create_and_get():
    manager = SessionManager(timeout=60)
    session = manager.create_session("Bob")
    
    # Vérifie qu'on peut la récupérer par son id
    retrieved = manager.get_session(session.session_id)
    assert retrieved is session
    assert retrieved.player_name == "Bob"


def test_session_manager_get_unknown_session():
    manager = SessionManager()
    assert manager.get_session("id-qui-n-existe-pas") is None


def test_session_manager_get_expired_session_auto_cleanup(monkeypatch):
    set_time(monkeypatch, 100)
    manager = SessionManager(timeout=50)
    session = manager.create_session("Charlie")
    
    # Le joueur se déconnecte
    session.handle_disconnect()
    
    # On avance le temps au-delà du timeout (100 + 51 = 151)
    set_time(monkeypatch, 151)
    
    # Récupérer la session doit renvoyer None et la supprimer du manager
    assert manager.get_session(session.session_id) is None
    assert session.session_id not in manager.sessions


def test_session_manager_clean_expired_sessions(monkeypatch):
    set_time(monkeypatch, 100)
    manager = SessionManager(timeout=30)
    
    s1 = manager.create_session("Alice") # Reste active
    s2 = manager.create_session("Bob")   # Expire
    
    s2.handle_disconnect()
    
    # On avance le temps de 31 secondes
    set_time(monkeypatch, 131)
    
    manager.clean_expired_sessions()
    
    # Alice doit toujours être là, Bob doit avoir été supprimé
    assert manager.get_session(s1.session_id) is not None
    assert manager.get_session(s2.session_id) is None