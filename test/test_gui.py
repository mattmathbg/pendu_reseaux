from client.gui import HangmanApp


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
