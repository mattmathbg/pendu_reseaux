import os
import sys
import time
import asyncio
import pytest
import customtkinter as ctk
import tkinter as tk
from unittest.mock import MagicMock
from client.gui import HangmanApp, THEME
from client.connection import GameClient
from protocol.message import Message
from server.server import Server


class FakeRoot:
    def __init__(self) -> None:
        self.next_after_id = 0
        self.callbacks = {}
        self.cancelled = []

    def after(self, delay: int, callback) -> str:
        self.next_after_id += 1
        after_id = str(self.next_after_id)
        self.callbacks[after_id] = callback
        return after_id

    def after_cancel(self, after_id: str) -> None:
        self.cancelled.append(after_id)
        self.callbacks.pop(after_id, None)


class FakeStringVar:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


def make_app() -> HangmanApp:
    app = HangmanApp.__new__(HangmanApp)
    app.root = FakeRoot()
    app.timer_var = FakeStringVar()
    app._timer_started_at = None
    app._timer_after_id = None
    return app


def test_timer_updates_and_stops_with_elapsed_time(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("client.gui.time.monotonic", lambda: now[0])
    app = make_app()

    app._start_timer()
    assert app.timer_var.value == "Temps : 00:00"

    now[0] = 165.0
    app.root.callbacks[app._timer_after_id]()
    assert app.timer_var.value == "Temps : 01:05"

    now[0] = 200.0
    assert app._stop_timer() == "01:40"
    assert app.timer_var.value == "Temps : 01:40"
    assert app._timer_started_at is None
    assert app._timer_after_id is None
    assert app.root.cancelled == ["2"]


def test_timer_formats_durations_over_an_hour():
    assert HangmanApp._format_elapsed(3_661.0) == "61:01"


@pytest.fixture(scope="module")
def shared_tk():
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def app_instance(shared_tk):
    for child in shared_tk.winfo_children():
        child.destroy()
    app = HangmanApp(shared_tk)
    return app


def test_gui_initialization(app_instance):
    assert len(app_instance.buttons) == 26
    assert app_instance.canvas is not None
    assert app_instance.word_var.get() == "_ _ _ _ _"
    assert "6 / 6" in app_instance.info_var.get()
    assert app_instance.client is not None
    assert app_instance.tabview is not None


def test_update_from_state_in_progress(app_instance):
    resp = Message(
        type="STATE",
        request_id=1,
        session_id="s123",
        payload={
            "masked_word": "_ E _ _ _",
            "errors_left": 5,
            "max_errors": 6,
            "used_letters": ["E", "X"],
            "status": "EN_COURS",
        },
    )
    app_instance.update_from_state(resp)
    assert "E" in app_instance.word_var.get()
    assert app_instance.lives_var.get() == "❤️ 5 / 6"
    assert app_instance.errors_var.get() == "💀 1 / 6"
    assert app_instance.buttons["E"]["state"] == "disabled"
    assert app_instance.buttons["X"]["state"] == "disabled"
    assert app_instance.buttons["A"]["state"] == "normal"


def test_update_from_state_game_over(app_instance, monkeypatch):
    monkeypatch.setattr("client.gui.messagebox.showinfo", lambda title, msg: None)

    resp = Message(
        type="STATE",
        request_id=2,
        session_id="s123",
        payload={
            "masked_word": "P E N D U",
            "errors_left": 4,
            "max_errors": 6,
            "used_letters": ["P", "E", "N", "D", "U"],
            "status": "GAGNE",
            "secret_word": "PENDU",
        },
    )
    app_instance.update_from_state(resp)
    for btn in app_instance.buttons.values():
        assert btn["state"] == "disabled"


def test_draw_hangman_stages(app_instance):
    for stage in range(7):
        app_instance._draw_hangman_stage(stage)
    app_instance._draw_hangman_stage(0, status="GAGNE")


def test_async_queue_and_logging(app_instance):
    app_instance.log_network_event("ENVOI", "test frame 123")
    app_instance._process_gui_queue()
    content = app_instance.log_text.get("1.0", "end")
    assert "test frame 123" in content
    assert "[ENVOI]" in content


def test_inspector_toggle_and_clear(app_instance):
    assert app_instance.inspector_visible is True
    app_instance._toggle_inspector()
    assert app_instance.inspector_visible is False
    app_instance._toggle_inspector()
    assert app_instance.inspector_visible is True

    app_instance.log_network_event("INFO", "msg to clear")
    app_instance._process_gui_queue()
    app_instance._clear_logs()
    assert app_instance.log_text.get("1.0", "end").strip() == ""


def test_key_press_handling(app_instance):
    mock_play = MagicMock()
    app_instance.play = mock_play

    event = MagicMock()
    event.char = "k"
    app_instance._on_key_press(event)
    mock_play.assert_called_once_with("K")


def test_dark_light_mode_toggle(app_instance):
    initial = ctk.get_appearance_mode().lower()
    app_instance._toggle_appearance_mode()
    toggled = ctk.get_appearance_mode().lower()
    assert toggled != initial
    app_instance._toggle_appearance_mode()
    assert ctk.get_appearance_mode().lower() == initial


def test_rooms_and_chat_tabs(app_instance):
    # Test chat send
    app_instance.chat_entry.insert(0, "Bonjour tout le monde")
    app_instance._send_chat_message()
    assert any("Bonjour tout le monde" in msg["text"] for msg in app_instance.chat_history)

    # Test create room
    app_instance.new_room_entry.insert(0, "Salon Test M1")
    app_instance._create_room_action()
    assert app_instance.current_room_name == "Salon Test M1"
    assert "Salon Test M1" in app_instance.room_badge_var.get()


@pytest.mark.asyncio
async def test_gui_async_integration_with_real_server(shared_tk):
    """Vérifie l'interaction asynchrone non-bloquante du GUI avec le serveur TCP réel."""
    server_instance = Server(host="127.0.0.1", port=0)
    server = await asyncio.start_server(
        server_instance.recv, server_instance.host, server_instance.port
    )
    port = server.sockets[0].getsockname()[1]

    for child in shared_tk.winfo_children():
        child.destroy()

    app = HangmanApp(shared_tk, client=GameClient(host="127.0.0.1", port=port))
    app.host_var.set("127.0.0.1")
    app.port_var.set(str(port))
    app.pseudo_var.set("GuiPlayer")

    async with server:
        # 1. Connect via GUI
        app.connect_or_disconnect()

        start = time.time()
        while time.time() - start < 3.0:
            app._process_gui_queue()
            if "GuiPlayer" in app.session_info_label.cget("text"):
                break
            await asyncio.sleep(0.05)

        assert app.client.is_connected()
        assert app.client.session_id is not None
        assert "GuiPlayer" in app.session_info_label.cget("text")

        # 2. Jouer une lettre via app.play()
        app.play("E")
        start = time.time()
        while time.time() - start < 3.0:
            app._process_gui_queue()
            if app.buttons["E"]["state"] == "disabled":
                break
            await asyncio.sleep(0.05)

        assert app.buttons["E"]["state"] == "disabled"

        # 3. Quitter proprement
        app.client.close()
