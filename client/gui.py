import os
import queue
import sys
import threading
import time
from datetime import datetime
from string import ascii_uppercase
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from client.connection import GameClient
from client.controller import GameController
from protocol.discovery import discover_servers

# Résolution des bibliothèques Tcl/Tk sous Windows si nécessaire
for _var, _sub in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
    _path = os.path.join(sys.prefix, "tcl", _sub)
    if _var not in os.environ and os.path.exists(_path):
        os.environ[_var] = _path

END_MESSAGES = {
    "GAGNE": "🎉 Félicitations ! Vous avez trouvé le mot !",
    "PERDU": "💀 Dommage, vous avez épuisé tous vos essais...",
    "ABANDONNE": "Partie abandonnée.",
}
THEME = {"key": ("#3B8ED0", "#1F6AA5"), "ok": "#16A34A", "bad": "#DC2626"}
MONO = "Consolas"

# Potence en texte : une étape par nombre d'erreurs (0 à 6)
HANGMAN_STAGES = [
    "  +---+\n  |   |\n      |\n      |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n      |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n  |   |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|   |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n /    |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n / \\  |\n      |\n=========",
]


def _w(kind, parent, pack=None, **kw):
    """Crée un widget, le place avec pack() et le renvoie."""
    widget = kind(parent, **kw)
    widget.pack(**({"side": "left", "padx": 3} if pack is None else pack))
    return widget


class HangmanApp:
    def __init__(self, root: ctk.CTk | None = None, client: GameClient | None = None) -> None:
        if root is None:
            ctk.set_appearance_mode("dark")
            root = ctk.CTk()
        self.root = root
        self.client = client or GameClient("127.0.0.1", 8888)
        self.controller = GameController(self.client)
        self._gui_queue: queue.Queue = queue.Queue()
        self._timer_started_at: float | None = None
        self._timer_after_id: str | None = None
        self.current_room_id: str | None = None
        self.chat_history: list[dict] = []

        self.host_var = tk.StringVar(value=self.client.host)
        self.port_var = tk.StringVar(value=str(self.client.port))
        self.pseudo_var = tk.StringVar(value=self.client.player_name or "Joueur")
        self.word_var = tk.StringVar(value="_ _ _ _ _")
        self.timer_var = tk.StringVar(value="Temps : 00:00")
        self.info_var = tk.StringVar(value="Essais restants : 6 / 6")
        self.lives_var = tk.StringVar(value="❤️ 6 / 6")
        self.errors_var = tk.StringVar(value="💀 0 / 6")
        self.hangman_var = tk.StringVar(value=HANGMAN_STAGES[0])
        self.room_var = tk.StringVar(value="Salon : aucun")

        self.root.title("Pendu Réseau")
        self.root.geometry("900x720")
        self._build_ui()
        self.client.log_callback = self.log_network_event
        self.root.bind("<Key>", self._on_key_press)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._check_saved_session()
        if self.client.is_connected():
            self._mark_connected()
        self.root.after(30, self._process_gui_queue)
        self.root.after(200, self._refresh)

    # --- INTERFACE ---

    def _build_ui(self) -> None:
            # Connexion
            top = _w(ctk.CTkFrame, self.root, {"fill": "x", "padx": 8, "pady": 6}, fg_color="transparent")
            for label, var, width in (("Port", self.port_var, 60), ("Pseudo", self.pseudo_var, 100)):
                _w(ctk.CTkLabel, top, text=label)
                _w(ctk.CTkEntry, top, textvariable=var, width=width).bind("<Return>", lambda _: self.connect_or_disconnect())
            self.connect_btn = _w(ctk.CTkButton, top, text="Connexion", width=100, command=self.connect_or_disconnect)
            self.resume_btn = _w(ctk.CTkButton, top, text="Reprendre", width=90, command=self.resume_existing_session)
            self.discover_btn = _w(ctk.CTkButton, top, text="Découvrir", width=90, command=self.discover_local_servers)
            _w(ctk.CTkLabel, top, {"side": "right"}, textvariable=self.room_var)
            self.session_info_label = _w(ctk.CTkLabel, self.root, {"anchor": "w", "padx": 10}, text="Déconnecté")

            self.tabview = _w(ctk.CTkTabview, self.root, {"fill": "both", "expand": True, "padx": 8, "pady": 4})
            game, chat, log = (self.tabview.add(name) for name in ("Jeu", "Chat", "Réseau"))

            # Onglet Jeu
            _w(ctk.CTkLabel, game, {"pady": 4}, textvariable=self.hangman_var, font=(MONO, 14), justify="left")
            _w(ctk.CTkLabel, game, {}, textvariable=self.word_var, font=(MONO, 32, "bold"))
            stats = _w(ctk.CTkFrame, game, {}, fg_color="transparent")
            for var in (self.timer_var, self.lives_var, self.errors_var):
                _w(ctk.CTkLabel, stats, {"side": "left", "padx": 10}, textvariable=var)
            _w(ctk.CTkLabel, game, {}, textvariable=self.info_var)
            keys = _w(ctk.CTkFrame, game, {"pady": 6}, fg_color="transparent")
            self.buttons: dict[str, ctk.CTkButton] = {}
            for i, letter in enumerate(ascii_uppercase):
                self.buttons[letter] = ctk.CTkButton(keys, text=letter, width=40, command=lambda l=letter: self.play(l))
                self.buttons[letter].grid(row=i // 9, column=i % 9, padx=2, pady=2)
            actions = _w(ctk.CTkFrame, game, {}, fg_color="transparent")
            for text, command in (("Nouvelle manche", self.start_new_game), ("Abandonner", self.quit_game)):
                _w(ctk.CTkButton, actions, text=text, command=command)

            # Onglet Chat
            self.chat_scope_seg = _w(ctk.CTkSegmentedButton, chat, {"anchor": "e"},
                                    values=["Salon Courant", "Chat Global"],
                                    command=lambda _: self._refresh_chat_display())
            self.chat_scope_seg.set("Salon Courant")
            self.chat_box = _w(ctk.CTkTextbox, chat, {"fill": "both", "expand": True, "pady": 4}, state="disabled")
            send_row = _w(ctk.CTkFrame, chat, {"fill": "x"}, fg_color="transparent")
            self.chat_entry = _w(ctk.CTkEntry, send_row, {"side": "left", "fill": "x", "expand": True},
                                placeholder_text="Votre message...")
            self.chat_entry.bind("<Return>", lambda _: self._send_chat_message())
            _w(ctk.CTkButton, send_row, text="Envoyer", width=80, command=self._send_chat_message)
            room_row = _w(ctk.CTkFrame, chat, {"fill": "x", "pady": 4}, fg_color="transparent")
            self.room_entry = _w(ctk.CTkEntry, room_row, width=240, placeholder_text="Nom du salon (1 à 20 caractères)")
            _w(ctk.CTkButton, room_row, text="Rejoindre", width=90, command=self._join_room_from_entry)
            _w(ctk.CTkButton, room_row, text="Quitter le salon", width=120, command=self._leave_room_action)

            # Onglet Réseau (inspecteur de trames)
            _w(ctk.CTkButton, log, {"anchor": "e"}, text="Effacer", width=80, command=self._clear_logs)
            self.log_text = _w(ctk.CTkTextbox, log, {"fill": "both", "expand": True}, font=(MONO, 12))

    # --- STATUT, SESSION ---

    def _status(self, text: str) -> None:
        self.session_info_label.configure(text=text)

    def _mark_connected(self) -> None:
        c = self.client
        self.connect_btn.configure(text="Déconnecter")
        self._status(f"Connecté à {c.host}:{c.port} | Session : {(c.session_id or '')[:8]}... | Joueur : {c.player_name}")

    def _check_saved_session(self) -> None:
        sessions = self.client._read_sessions("session.json")
        found = bool(sessions)
        self.resume_btn.configure(state="normal" if found else "disabled")
        if found:
            self._status(f"Sessions disponibles : {', '.join(sessions)}")

    def _target(self) -> tuple[str, int] | None:
        try:
            return self.host_var.get().strip() or "127.0.0.1", int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Port invalide", "Entrez un numéro de port valide (ex : 8888).")
            return None

    def _do(self, action, *args, title: str = "Erreur"):
        """Appelle le contrôleur. Renvoie la réponse, ou None si le réseau est coupé ou si le serveur répond ERROR."""
        try:
            resp = action(*args)
        except (ConnectionError, OSError) as exc:
            self._status("Déconnecté")
            messagebox.showerror(title, str(exc))
            return None
        if resp.type == "ERROR":
            messagebox.showwarning(title, f"{resp.payload.get('code')} : {resp.payload.get('message')}")
            return None
        return resp

    def _read_port(self) -> int | None:
        try:
            return int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Port invalide", "Entrez un numéro de port valide (ex : 8888).")
            return None

    # --- CONNEXION, REPRISE, DÉCOUVERTE ---

    def connect_or_disconnect(self) -> None:
        if self.client.is_connected():
            self.client.close()
            self.connect_btn.configure(text="Connexion")
            self._status("Déconnecté")
        else:
            self._login()

    def _login(self) -> None:
        port = self._read_port()
        if port is None:
            return
        pseudo = self.pseudo_var.get().strip() or "Joueur"
        endpoints = getattr(self, "selected_endpoints", None) or [{"host": "127.0.0.1"}]
        if self._do(self.controller.connect, endpoints, port, pseudo, title="Connexion impossible") is None:
            return
        self._mark_connected()
        self.client.save_session("session.json")
        self.resume_btn.configure(state="normal")
        self.start_new_game()

    def resume_existing_session(self) -> None:
        port = self._read_port()
        if port is None:
            return
        pseudo = self.pseudo_var.get().strip()
        if not self.client.session_id and not self.client.load_session(pseudo, "session.json"):
            messagebox.showinfo("Aucune session", f"Aucune session enregistrée pour « {pseudo} ».")
            return
        endpoints = getattr(self, "selected_endpoints", None) or [{"host": "127.0.0.1"}]
        resp = self._do(self.controller.resume, endpoints, port, title="Reprise impossible")
        if resp is None:
            return
        self._mark_connected()
        if resp.payload.get("status") == "IDLE":
            self.start_new_game()
        else:
            self.update_from_state(resp)

    def discover_local_servers(self) -> None:
        self.discover_btn.configure(state="disabled", text="Recherche...")

        def work() -> None:
            try:
                result = discover_servers(timeout=1.2)
            except Exception as exc:
                result = exc
            self._gui_queue.put(lambda: self._on_discovered(result))

        threading.Thread(target=work, daemon=True).start()

    def _on_discovered(self, result) -> None:
        self.discover_btn.configure(state="normal", text="Découvrir")
        if isinstance(result, Exception):
            messagebox.showerror("Découverte", str(result))
        elif not result:
            messagebox.showinfo("Découverte", "Aucun serveur de Pendu trouvé sur le réseau local.")
        elif len(result) == 1:
            self._apply_server(result[0])
        else:
            dialog = ctk.CTkToplevel(self.root)
            dialog.title("Serveurs détectés")
            dialog.transient(self.root)
            for s in result:
                ctk.CTkButton(dialog, text=s["display"],
                              command=lambda s=s: (self._apply_server(s), dialog.destroy())).pack(padx=10, pady=4)

    def _apply_server(self, s: dict) -> None:
        self.selected_endpoints = s["endpoints"]
        self.port_var.set(str(s["port"]))
        self.info_var.set(f"Serveur sélectionné : {s['display']}")

    # --- PARTIE ---

    def start_new_game(self) -> None:
        if not self.client.is_connected() or not self.client.session_id:
            self.client.close()
            self._login()
            return
        self._keys(state="normal", fg_color=THEME["key"])
        resp = self._do(self.controller.new_game)
        if resp is not None:
            self.update_from_state(resp)

    def play(self, letter: str) -> None:
        resp = self._do(self.controller.guess, letter.upper())
        if resp is not None:
            self.update_from_state(resp)

    def quit_game(self) -> None:
        if not messagebox.askyesno("Abandonner", "Voulez-vous vraiment abandonner la partie ?"):
            return
        if self._do(self.controller.quit_game) is None:
            return
        self._stop_timer()
        self._status("Session clôturée")
        self.info_var.set("Partie abandonnée.")
        self._set_room(None)
        self._keys(state="disabled")

    def update_from_state(self, resp) -> None:
        p = resp.payload
        max_errors = p.get("max_errors", 6)
        masked = p.get("masked_word", "")
        self.word_var.set("  ".join(masked.replace(" ", "")))
        left = p.get("errors_left", max_errors)
        made = max(0, max_errors - left)
        self.lives_var.set(f"❤️ {left} / {max_errors}")
        self.errors_var.set(f"💀 {made} / {max_errors}")
        self.info_var.set(f"Essais restants : {left} / {max_errors}  (Erreurs : {made})")
        status = p.get("status")
        self._show_hangman(made, status)
        for letter in p.get("used_letters", []):
            key = letter.upper()
            if key in self.buttons:
                self.buttons[key].configure(state="disabled", fg_color=THEME["ok"] if key in masked else THEME["bad"])
        if status == "EN_COURS" and self._timer_started_at is None:
            self._start_timer()
        elif status in END_MESSAGES:
            self._end_game(p, status)

    def _end_game(self, p: dict, status: str) -> None:
        elapsed = self._stop_timer()
        self._keys(state="disabled")
        text = END_MESSAGES[status] + (f"\n\n⏱ Temps écoulé : {elapsed}" if elapsed else "")
        if status == "PERDU" and p.get("secret_word"):
            text += f"\n\n📖 Le mot était : {p['secret_word']}"
        self.info_var.set(END_MESSAGES[status])
        messagebox.showinfo("Fin de partie", text)

    def _keys(self, **config) -> None:
        for button in self.buttons.values():
            button.configure(**config)

    def _show_hangman(self, errors_made: int, status: str | None = None) -> None:
        text = HANGMAN_STAGES[min(errors_made, len(HANGMAN_STAGES) - 1)]
        self.hangman_var.set(text + ("\n   Gagné !" if status == "GAGNE" else ""))

    def _on_key_press(self, event: tk.Event) -> None:
        """Permet de jouer avec le clavier physique (sauf pendant une saisie de texte)."""
        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, tk.Text)) or "entry" in str(focused).lower():
            return
        char = (event.char or "").upper()
        if char in self.buttons and self.buttons[char].cget("state") == "normal":
            self.play(char)

    # --- MINUTERIE ---

    @staticmethod
    def _format_elapsed(elapsed: float) -> str:
        minutes, seconds = divmod(int(elapsed), 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _start_timer(self) -> None:
        if self._timer_after_id is not None:
            self.root.after_cancel(self._timer_after_id)
        self._timer_started_at = time.monotonic()
        self.timer_var.set("Temps : 00:00")
        self._timer_after_id = self.root.after(200, self._tick_timer)

    def _tick_timer(self) -> None:
        self._timer_after_id = None
        if self._timer_started_at is None:
            return
        elapsed = time.monotonic() - self._timer_started_at
        self.timer_var.set(f"Temps : {self._format_elapsed(elapsed)}")
        self._timer_after_id = self.root.after(200, self._tick_timer)

    def _stop_timer(self) -> str | None:
        if self._timer_started_at is None:
            return None
        elapsed = self._format_elapsed(time.monotonic() - self._timer_started_at)
        self._timer_started_at = None
        if self._timer_after_id is not None:
            self.root.after_cancel(self._timer_after_id)
            self._timer_after_id = None
        self.timer_var.set(f"Temps : {elapsed}")
        return elapsed

    # --- CHAT ET SALONS ---

    def _visible_messages(self) -> list[dict]:
        """Messages affichés selon la portée choisie (salon courant ou global)."""
        if self.chat_scope_seg.get() == "Chat Global":
            return [m for m in self.chat_history if m["scope"] == "global"]
        return [m for m in self.chat_history if m["scope"] == "room" and m["room_id"] == self.current_room_id]

    def _refresh_chat_display(self) -> None:
        self.chat_box.configure(state="normal")
        self.chat_box.delete("1.0", "end")
        for m in self._visible_messages():
            self.chat_box.insert("end", f"[{m['time']}] {m['sender']} : {m['text']}\n")
        self.chat_box.configure(state="disabled")
        self.chat_box.see("end")

    def _add_chat_line(self, payload: dict) -> None:
        """Ajoute un message (push reçu ou réponse à mon envoi) à l'historique."""
        self.chat_history.append({
            "sender": payload.get("player", "?"),
            "text": payload.get("text", ""),
            "time": datetime.now().strftime("%H:%M:%S"),
            "scope": payload.get("scope", "global"),
            "room_id": payload.get("room_id"),
        })
        self._refresh_chat_display()

    def _send_chat_message(self) -> None:
        text = self.chat_entry.get().strip()
        if not text:
            return
        scope = "room" if self.chat_scope_seg.get() == "Salon Courant" else "global"
        resp = self._do(self.controller.chat, text, scope, title="Chat")
        if resp is not None:
            self.chat_entry.delete(0, "end")
            self._add_chat_line(resp.payload)  # l'expéditeur ne reçoit pas son propre push

    def _join_room_from_entry(self) -> None:
        name = self.room_entry.get().strip()
        if not name:
            return
        resp = self._do(self.controller.join_room, name, title="Salon")
        if resp is not None:
            self.room_entry.delete(0, "end")
            self._set_room(resp.payload.get("room_id"))

    def _leave_room_action(self) -> None:
        if self._do(self.controller.leave_room, title="Salon") is not None:
            self._set_room(None)

    def _set_room(self, room_id: str | None) -> None:
        self.current_room_id = room_id
        self.room_var.set(f"Salon : {room_id or 'aucun'}")
        self._refresh_chat_display()

    # --- LOGS RÉSEAU, BOUCLES PÉRIODIQUES ---

    def log_network_event(self, direction: str, text: str) -> None:
        self.log_text.insert("end", f"[{direction}] {text}\n")
        self.log_text.see("end")

    def _clear_logs(self) -> None:
        self.log_text.delete("1.0", "end")

    def _process_gui_queue(self) -> None:
        """Exécute, dans le thread de l'interface, les callbacks envoyés par le thread de découverte."""
        while not self._gui_queue.empty():
            self._gui_queue.get_nowait()()
        self.root.after(30, self._process_gui_queue)

    def _refresh(self) -> None:
        """Relit le réseau sans bloquer (chat en direct), puis se reprogramme."""
        try:
            for message in self.controller.poll():
                self._add_chat_line(message)
        except (ConnectionError, OSError):
            self.client.close()
            self._status("Déconnecté")
        self.root.after(200, self._refresh)

    def _on_close(self) -> None:
        if self.client.is_connected() and self.client.player_name and self.client.session_id:
            self.client.save_session("session.json")   # met à jour last_seen
        self.client.close()
        self.root.destroy()


def main() -> None:
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    HangmanApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()