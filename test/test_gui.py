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
from server.server import Server, create_server_ssl_context
import threading


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

@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """Empêche les boîtes de dialogue de bloquer les tests."""
    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(f"client.gui.messagebox.{name}", lambda *a, **k: None)
    monkeypatch.setattr("client.gui.messagebox.askyesno", lambda *a, **k: True)


def test_gui_initialization(app_instance):
    assert len(app_instance.buttons) == 26
    assert app_instance.word_var.get() == "_ _ _ _ _"
    assert "6 / 6" in app_instance.info_var.get()
    assert app_instance.client is not None
    assert app_instance.tabview is not None
    assert app_instance.client.use_tls is True
    assert hasattr(app_instance, "tls_label")
    assert hasattr(app_instance, "category_menu")
    assert app_instance.category_var.get() == "Toutes (Aléatoire)"


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
    assert app_instance.buttons["E"].cget("state") == "disabled"
    assert app_instance.buttons["X"].cget("state") == "disabled"
    assert app_instance.buttons["A"].cget("state") == "normal"
    assert app_instance.new_game_btn.cget("state") == "disabled"
    assert app_instance.new_game_btn.cget("fg_color") == THEME["disabled"]


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
        assert btn.cget("state") == "disabled"
    assert app_instance.new_game_btn.cget("state") == "normal"
    assert app_instance.new_game_btn.cget("fg_color") == THEME["key"]


def test_hangman_text_stage(app_instance):
    app_instance._show_hangman(0)
    first = app_instance.hangman_var.get()
    app_instance._show_hangman(6)
    assert app_instance.hangman_var.get() != first


def test_async_queue_and_logging(app_instance):
    app_instance.log_network_event("ENVOI", "test frame 123")
    app_instance._process_gui_queue()
    content = app_instance.log_text.get("1.0", "end")
    assert "test frame 123" in content
    assert "[ENVOI]" in content


def test_clear_logs(app_instance):
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




def test_chat_tab_has_room_bar_and_filters(app_instance):
    assert hasattr(app_instance, "room_entry")
    app_instance._add_chat_line({"player": "Bob", "text": "salut", "scope": "global", "room_id": None})
    app_instance._add_chat_line({"player": "Alice", "text": "dans le salon", "scope": "room", "room_id": "salon1"})
    app_instance.current_room_id = "salon1"
    app_instance.chat_scope_seg.set("Salon Courant")
    assert [m["text"] for m in app_instance._visible_messages()] == ["dans le salon"]


@pytest.fixture
def real_server():
    """Serveur TCP réel dans un thread séparé, avec sa propre boucle asyncio et TLS."""
    srv = Server(host="127.0.0.1", port=0, use_tls=True)
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    holder = {}

    async def boot():
        ssl_ctx = create_server_ssl_context()
        holder["server"] = await asyncio.start_server(srv.recv, "127.0.0.1", 0, ssl=ssl_ctx)
        holder["port"] = holder["server"].sockets[0].getsockname()[1]
        ready.set()
        await holder["server"].serve_forever()

    def run():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(boot())
        except asyncio.CancelledError:
            pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(timeout=2), "serveur de test non démarré"
    yield holder["port"]
    loop.call_soon_threadsafe(holder["server"].close)
    thread.join(timeout=2)


def test_gui_connects_and_plays_on_real_server(app_instance, real_server, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # évite d'écrire un session.json dans le projet
    app = app_instance
    app.host_var.set("127.0.0.1")
    app.port_var.set(str(real_server))
    app.pseudo_var.set("GuiPlayer")

    app.connect_or_disconnect()   # connexion, HELLO, NEW_GAME, tout en synchrone

    assert app.client.is_connected()
    assert app.client.session_id is not None
    assert "GuiPlayer" in app.session_info_label.cget("text")

    app.play("E")
    assert app.buttons["E"].cget("state") == "disabled"

    app.client.close()


def test_gui_apply_discovered_server_sets_tls(app_instance):
    assert hasattr(app_instance, "tls_label")
    server_info = {
        "endpoints": [{"host": "192.168.1.100", "family": "IPv4"}],
        "port": 8888,
        "server_name": "Docker TLS",
        "players_count": 1,
        "use_tls": True,
        "display": "Docker TLS [TLS 🔒] — 1 joueur",
    }
    app_instance._apply_server(server_info)
    assert app_instance.selected_endpoints == [{"host": "192.168.1.100", "family": "IPv4"}]
    assert app_instance.port_var.get() == "8888"
    assert app_instance.client.use_tls is True


def test_gui_category_selection_in_new_game(app_instance):
    dummy_resp = Message(type="STATE", request_id=1, payload={"masked_word": "_", "status": "EN_COURS", "category": "LES ANIMAUX"})
    mock_new_game = MagicMock(return_value=dummy_resp)
    app_instance.controller.new_game = mock_new_game
    app_instance.client.is_connected = lambda: True
    app_instance.client.session_id = "sess-1"

    app_instance.category_var.set("Animaux")
    assert app_instance._get_selected_category_id() == 19

    app_instance.start_new_game()
    mock_new_game.assert_called_once_with(19)
    assert "ANIMAUX" in app_instance.theme_var.get()


def test_gui_timeout_error_resyncs_and_reenables_new_game(app_instance):
    app_instance.update_from_state(
        Message(
            type="STATE",
            request_id=1,
            payload={"masked_word": "_ _ _", "errors_left": 6, "max_errors": 6, "used_letters": [], "status": "EN_COURS"},
        )
    )
    assert app_instance.new_game_btn.cget("state") == "disabled"
    assert app_instance._timer_started_at is not None

    timeout_resp = Message(
        type="ERROR",
        request_id=2,
        payload={
            "code": "TIMEOUT",
            "message": "Délai dépassé.",
            "masked_word": "_ _ _",
            "errors_left": 6,
            "max_errors": 6,
            "used_letters": [],
            "status": "PERDU",
            "secret_word": "SOL",
        },
    )
    app_instance.controller.guess = MagicMock(return_value=timeout_resp)
    app_instance.play("A")

    assert app_instance._timer_started_at is None
    assert app_instance.new_game_btn.cget("state") == "normal"
    assert app_instance.new_game_btn.cget("fg_color") == THEME["key"]
    for btn in app_instance.buttons.values():
        assert btn.cget("state") == "disabled"
