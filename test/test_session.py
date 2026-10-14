from types import SimpleNamespace
import uuid

import pytest

import core.session as session_module
from core.session import GameSession


def set_time(monkeypatch, value):
	monkeypatch.setattr(session_module, "time", SimpleNamespace(time=lambda: value))


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


def test_saving_response_replaces_previous_cached_response():
	session = GameSession("Alice")
	session.save_response(1, {"value": "old"})
	session.save_response(2, {"value": "new"})

	assert session.get_cached_response(1) is None
	assert session.get_cached_response(2) == {"value": "new"}


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


def test_disconnected_session_without_timestamp_is_expired():
	session = GameSession("Alice")
	session.is_connected = False

	assert session.is_expired() is True


@pytest.mark.parametrize("elapsed, timeout, expected", [(4, 5, False), (6, 5, True)])
def test_is_expired_respects_custom_timeout(monkeypatch, elapsed, timeout, expected):
	set_time(monkeypatch, 20)
	session = GameSession("Alice")
	session.handle_disconnect()
	set_time(monkeypatch, 20 + elapsed)

	assert session.is_expired(timeout=timeout) is expected
