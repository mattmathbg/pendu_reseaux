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
from core.words import CATEGORIES
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
THEME = {"key": ("#3B8ED0", "#1F6AA5"), "ok": "#16A34A", "bad": "#DC2626", "disabled": ("#9CA3AF", "#4B5563")}
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
        self.client = client or GameClient("127.0.0.1", 8888, use_tls=True)
        self.client.use_tls = True
        self.controller = GameController(self.client)
        self._gui_queue: queue.Queue = queue.Queue()
        self._timer_started_at: float | None = None
        self._timer_after_id: str | None = None
        self.chat_history: list[dict] = []
        self._duel_id: str | None = None

        self.host_var = tk.StringVar(value=self.client.host)
        self.port_var = tk.StringVar(value=str(self.client.port))
        self.pseudo_var = tk.StringVar(value=self.client.player_name or "Joueur")
        self.tls_var = tk.BooleanVar(value=True)
        self.word_var = tk.StringVar(value="_ _ _ _ _")
        self.timer_var = tk.StringVar(value="Temps : 00:00")
        self.info_var = tk.StringVar(value="Essais restants : 6 / 6")
        self.theme_var = tk.StringVar(value="Catégorie : -")
        self.category_var = tk.StringVar(value=CATEGORIES[0])
        self.lives_var = tk.StringVar(value="❤️ 6 / 6")
        self.errors_var = tk.StringVar(value="💀 0 / 6")
        self.hangman_var = tk.StringVar(value=HANGMAN_STAGES[0])
        self.room_var = tk.StringVar(value="Aucun duel en cours")

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
            _w(ctk.CTkLabel, top, text="Pseudo")
            _w(ctk.CTkEntry, top, textvariable=self.pseudo_var, width=120).bind("<Return>", lambda _: self.connect_or_disconnect())
            self.tls_label = _w(ctk.CTkLabel, top, text="TLS 🔒", text_color="#10B981", font=(MONO, 12, "bold"))
            self.connect_btn = _w(ctk.CTkButton, top, text="Connexion", width=100, command=self.connect_or_disconnect)
            self.discover_btn = _w(ctk.CTkButton, top, text="Découvrir", width=90, command=self.discover_local_servers)
            self.session_info_label = _w(ctk.CTkLabel, self.root, {"anchor": "w", "padx": 10}, text="Déconnecté")

            self.tabview = _w(ctk.CTkTabview, self.root, {"fill": "both", "expand": True, "padx": 8, "pady": 4})
            game, chat, log = (self.tabview.add(name) for name in ("Jeu", "Chat", "Réseau"))

            # Onglet Jeu
            self.hangman_label = _w(ctk.CTkLabel, game, {"pady": 4}, textvariable=self.hangman_var, font=(MONO, 14), justify="left")
            self.word_label = _w(ctk.CTkLabel, game, {}, textvariable=self.word_var, font=(MONO, 32, "bold"))
            _w(ctk.CTkLabel, game, {"pady": 2}, textvariable=self.theme_var, font=(MONO, 13, "bold"), text_color="#38BDF8")
            stats = _w(ctk.CTkFrame, game, {}, fg_color="transparent")
            for var in (self.timer_var, self.lives_var, self.errors_var):
                _w(ctk.CTkLabel, stats, {"side": "left", "padx": 10}, textvariable=var)
            _w(ctk.CTkLabel, game, {}, textvariable=self.info_var)
            self.keys_frame = _w(ctk.CTkFrame, game, {"pady": 6}, fg_color="transparent")
            self.buttons: dict[str, ctk.CTkButton] = {}
            for i, letter in enumerate(ascii_uppercase):
                self.buttons[letter] = ctk.CTkButton(self.keys_frame, text=letter, width=40, command=lambda l=letter: self.play(l))
                self.buttons[letter].grid(row=i // 9, column=i % 9, padx=2, pady=2)
            self.actions_frame = _w(ctk.CTkFrame, game, {"pady": 4}, fg_color="transparent")
            _w(ctk.CTkLabel, self.actions_frame, text="Catégorie :")
            self.category_menu = _w(ctk.CTkOptionMenu, self.actions_frame, variable=self.category_var, values=list(CATEGORIES.values()), width=190)
            self.new_game_btn = _w(ctk.CTkButton, self.actions_frame, text="Nouvelle manche", command=self.start_new_game)
            self.quit_btn = _w(ctk.CTkButton, self.actions_frame, text="Abandonner", command=self.quit_game)
            duel_row = _w(ctk.CTkFrame, game, {"pady": 4}, fg_color="transparent")
            _w(ctk.CTkButton, duel_row, text="Créer un duel", command=self._create_duel_action)
            self.duel_entry = _w(ctk.CTkEntry, duel_row, width=180, placeholder_text="Code du duel (3-12 lettres)")
            _w(ctk.CTkButton, duel_row, text="Rejoindre", command=self._join_duel_action)
            _w(ctk.CTkLabel, game, {"pady": 2}, textvariable=self.room_var, text_color="#9CA3AF")
            self.board = _w(ctk.CTkFrame, game, {"fill": "both", "expand": True}, fg_color="transparent")
            

            # Onglet Chat (global uniquement)
            self.chat_box = _w(ctk.CTkTextbox, chat, {"fill": "both", "expand": True, "pady": 4}, state="disabled")
            send_row = _w(ctk.CTkFrame, chat, {"fill": "x"}, fg_color="transparent")
            self.chat_entry = _w(ctk.CTkEntry, send_row, {"side": "left", "fill": "x", "expand": True},
                                placeholder_text="Votre message...")
            self.chat_entry.bind("<Return>", lambda _: self._send_chat_message())
            _w(ctk.CTkButton, send_row, text="Envoyer", width=80, command=self._send_chat_message)

            # Onglet Réseau (inspecteur de trames)
            _w(ctk.CTkButton, log, {"anchor": "e"}, text="Effacer", width=80, command=self._clear_logs)
            self.log_text = _w(ctk.CTkTextbox, log, {"fill": "both", "expand": True}, font=(MONO, 12))
            self.hangman_label.pack_forget()
            self.keys_frame.pack_forget()
            self.board.pack_forget()
            self._keys(state="disabled")

    def _show_game_widgets(self) -> None:
        self.hangman_label.pack(pady=4, before=self.word_label)
        self.keys_frame.pack(pady=6, before=self.actions_frame)

    def _hide_game_widgets(self) -> None:
        self.hangman_label.pack_forget()
        self.keys_frame.pack_forget()

    # --- STATUT, SESSION ---

    def _status(self, text: str) -> None:
        self.session_info_label.configure(text=text)

    def _mark_connected(self) -> None:
        c = self.client
        self.connect_btn.configure(text="Déconnecter")
        self._status(f"Connecté à {c.host}:{c.port} | Session : {(c.session_id or '')[:8]}... | Joueur : {c.player_name}")

    def _check_saved_session(self) -> None:
        sessions = self.client._read_sessions("session.json")
        if sessions:
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
            self._set_new_game_enabled(True)
            messagebox.showerror(title, str(exc))
            return None
        if resp is None:
            return None
        if resp.type == "ERROR":
            if resp.payload.get("code") == "TIMEOUT":
                self._handle_timeout_error(resp.payload)
                return None
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
            self._set_new_game_enabled(True)
        else:
            self._login()

    def _login(self) -> None:
        port = self._read_port()
        if port is None:
            return
        pseudo = self.pseudo_var.get().strip() or "Joueur"
        endpoints = getattr(self, "selected_endpoints", None) or [{"host": "127.0.0.1"}]

        if self.client.load_session(pseudo):
            resp = self._do(self.controller.resume, endpoints, port, title="Reprise impossible")
            if resp is not None:
                self._mark_connected()
                if resp.payload.get("status") != "IDLE":
                    self.update_from_state(resp)
                return
            self.client.close()

        if self._do(self.controller.connect, endpoints, port, pseudo, title="Connexion impossible") is None:
            return
        self._mark_connected()
        self.client.save_session("session.json")

        if self._do(self.controller.connect, endpoints, port, pseudo, title="Connexion impossible") is None:
            return
        self._mark_connected()
        self.client.save_session("session.json")


    def resume_existing_session(self) -> None:
        port = self._read_port()
        if port is None:
            return
        pseudo = self.pseudo_var.get().strip()
        if not self.client.session_id and not self.client.load_session(pseudo, "session.json"):
            messagebox.showinfo("Aucune session", f"Aucune session enregistrée pour « {pseudo} ».")
            return
        self.client.use_tls = True
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
        self.client.use_tls = True
        self.info_var.set(f"Serveur sélectionné : {s['display']}")

    # --- PARTIE ---

    def _get_selected_category_id(self) -> int | None:
        selected_name = self.category_var.get()
        for cat_id, name in CATEGORIES.items():
            if name == selected_name and cat_id > 0:
                return cat_id
        return None

    def start_new_game(self) -> None:
        if not self.client.is_connected() or not self.client.session_id:
            self.client.close()
            self._login()
            return
        cat_id = self._get_selected_category_id()
        resp = self._do(self.controller.new_game, cat_id)
        if resp is not None:
            self.update_from_state(resp)

    def play(self, letter: str) -> None:
        resp = self._do(self.controller.guess, letter.upper())
        if resp is not None and resp.type in ("DUEL", "DUEL_END"):
            self._show_duel(resp.payload)
            if resp.type == "DUEL_END":
                messagebox.showinfo("Fin du duel", f"Vainqueur : {resp.payload.get('winner') or 'personne'}")
        elif resp is not None:
            self.update_from_state(resp)

    def quit_game(self) -> None:
        if not messagebox.askyesno("Abandonner", "Voulez-vous vraiment abandonner la partie ?"):
            return
        if self._do(self.controller.quit_game) is None:
            return
        self._stop_timer()
        self._status("Session clôturée")
        self.info_var.set("Partie abandonnée.")
        self._keys(state="disabled")
        self._hide_game_widgets()
        self.board.pack_forget()
        self._set_new_game_enabled(True)

    def _apply_state_payload(self, p: dict) -> str | None:
        """Met à jour les widgets de jeu depuis un payload d'état et renvoie le statut."""
        max_errors = p.get("max_errors", 6)
        masked = p.get("masked_word", "")
        self.word_var.set("  ".join(masked.replace(" ", "")))
        left = p.get("errors_left", max_errors)
        made = max(0, max_errors - left)
        self.lives_var.set(f"❤️ {left} / {max_errors}")
        self.errors_var.set(f"💀 {made} / {max_errors}")
        self.info_var.set(f"Essais restants : {left} / {max_errors}  (Erreurs : {made})")
        category = p.get("category")
        if category:
            self.theme_var.set(f"Catégorie : {category}")
        status = p.get("status")
        self._show_hangman(made, status)
        for letter in p.get("used_letters", []):
            key = letter.upper()
            if key in self.buttons:
                self.buttons[key].configure(state="disabled", fg_color=THEME["ok"] if key in masked else THEME["bad"])
        return status

    def update_from_state(self, resp) -> None:
        p = resp.payload
        if p.get("status") == "EN_COURS":
            self._keys(state="normal", fg_color=THEME["key"])
        status = self._apply_state_payload(p)
        if status == "EN_COURS":
            self._show_game_widgets()
        else:
            self._hide_game_widgets()
        self._set_new_game_enabled(status != "EN_COURS")
        if status == "EN_COURS" and self._timer_started_at is None:
            self._start_timer()
        elif status in END_MESSAGES:
            self._end_game(p, status)

    def _handle_timeout_error(self, p: dict) -> None:
        """Resynchronise l'interface lorsque le serveur prononce une défaite par TIMEOUT."""
        if "masked_word" in p:
            self._apply_state_payload(p)
        elapsed = self._stop_timer()
        self._keys(state="disabled")
        self._hide_game_widgets()
        self._set_new_game_enabled(True)
        self.info_var.set(END_MESSAGES["PERDU"])
        details = p.get("message") or "Délai maximal dépassé : la partie est perdue."
        if elapsed:
            details += f"\n\n⏱ Temps écoulé : {elapsed}"
        if p.get("secret_word"):
            details += f"\n\n📖 Le mot était : {p['secret_word']}"
        messagebox.showwarning("Temps dépassé", details)

    def _set_new_game_enabled(self, enabled: bool) -> None:
        """Active ou grise le bouton « Nouvelle manche » selon l'état de la partie."""
        if enabled:
            self.new_game_btn.configure(state="normal", fg_color=THEME["key"])
        else:
            self.new_game_btn.configure(state="disabled", fg_color=THEME["disabled"])

    def _end_game(self, p: dict, status: str) -> None:
        elapsed = self._stop_timer()
        self._keys(state="disabled")
        self._hide_game_widgets()
        text = END_MESSAGES[status] + (f"\n\n⏱ Temps écoulé : {elapsed}" if elapsed else "")
        if status == "PERDU" and p.get("secret_word"):
            text += f"\n\n📖 Le mot était : {p['secret_word']}"
        self.info_var.set(END_MESSAGES[status])
        messagebox.showinfo("Fin de partie", text)

    def _keys(self, **config) -> None:
        for button in self.buttons.values():
            button.configure(**config)

    def _disable_key(self, letter: str, fg: str, text: str) -> None:
        self.buttons[letter].configure(state="disabled", fg_color=fg, text_color=text)

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

    # --- CHAT GLOBAL ---

    def _visible_messages(self) -> list[dict]:
        """Messages affichés dans le chat global."""
        return [m for m in self.chat_history if m["scope"] == "global"]

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
        })
        self._refresh_chat_display()

    def _send_chat_message(self) -> None:
        text = self.chat_entry.get().strip()
        if not text:
            return
        resp = self._do(self.controller.chat, text, "global", title="Chat")
        if resp is not None:
            self.chat_entry.delete(0, "end")
            self._add_chat_line(resp.payload)  # l'expéditeur ne reçoit pas son propre push

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
                if message.get("type") in ("DUEL_STATE", "DUEL_END"):
                    self._show_duel(message)
                    if message["type"] == "DUEL_END":
                        messagebox.showinfo("Fin du duel", f"Vainqueur : {message.get('winner') or 'personne'}")
                else:
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

    def _create_duel_action(self) -> None:
        duel_id = self.duel_entry.get().strip().upper()
        if not duel_id:
            messagebox.showwarning("Créer un duel", "Choisissez un code de 3 à 12 lettres.")
            return
        if not duel_id.isascii() or not duel_id.isalpha() or not 3 <= len(duel_id) <= 12:
            messagebox.showwarning("Créer un duel", "Le code doit contenir uniquement 3 à 12 lettres A-Z.")
            return

        resp = self._do(self.controller.create_duel, duel_id, title="Duel")
        if resp is None:
            return
        if resp.type != "DUEL":
            messagebox.showwarning("Duel", "Réponse inattendue du serveur lors de la création du duel.")
            return
        server_duel_id = resp.payload.get("duel_id")
        if server_duel_id != duel_id:
            messagebox.showerror(
                "Serveur à mettre à jour",
                "Le serveur actif n'a pas pris en compte le code choisi. "
                "Ne partage pas l'autre code affiché par le serveur. "
                "Avec Docker, exécute `docker compose up -d --build`. "
                "Sinon, redémarre le serveur. Reconnecte-toi, puis recrée le duel.",
            )
            return
        self._duel_id = duel_id
        self._show_duel(resp.payload)
        messagebox.showinfo("Duel créé", f"Duel créé avec le code :\n\n{self._duel_id}\n\nVotre adversaire doit saisir ce même code.")

    def _join_duel_action(self) -> None:
        duel_id = self.duel_entry.get().strip().upper()
        if not duel_id:
            messagebox.showwarning(
                "Rejoindre un duel",
                "Saisissez le même code que celui choisi sur le client qui a créé le duel.",
            )
            return
        resp = self._do(self.controller.join_duel, duel_id, title="Duel")
        if resp is None:
            return
        if resp.type != "DUEL":
            messagebox.showwarning("Duel", "Réponse inattendue du serveur lors de la connexion au duel.")
            return
        self._duel_id = duel_id
        self._show_duel(resp.payload)
        messagebox.showinfo("Duel rejoint", "Vous avez rejoint la partie !")

    def _show_duel(self, p: dict) -> None:
        status = p.get("status", "INCONNU")
        players = " vs ".join(p.get("players", [])) or "Joueurs en attente"
        turn = p.get("turn")
        duel_id = p.get("duel_id", self._duel_id)
        if status == "EN_ATTENTE":
            self.room_var.set(f"Duel créé | Code : {duel_id} | En attente d'un adversaire")
        else:
            self.room_var.set(f"Duel {status} | Code : {duel_id} | {players} | Tour : {turn or '-'}")
        self.word_var.set("  ".join(p.get("masked_word", "").replace(" ", "")))

        max_errors = p.get("max_errors", 6)
        errors_left = p.get("errors_left", max_errors)
        made = max(0, max_errors - errors_left)
        self.errors_var.set(f"💀 {made} / {max_errors}")
        self.lives_var.set(f"❤️ {errors_left} / {max_errors}")
        self._show_hangman(made, status if status == "TERMINE" else None)

        if p.get("duel_id"):
            self._duel_id = p["duel_id"]
        if status == "EN_COURS":
            self._show_game_widgets()
            self._keys(state="disabled", fg_color=THEME["key"])
            if turn == self.client.player_name:
                self._keys(state="normal")
            if self._timer_started_at is None:
                self._start_timer()
        else:
            self._hide_game_widgets()
            self._keys(state="disabled")
            if self._timer_started_at is not None:
                self._stop_timer()

        for letter in p.get("used_letters", []):
            key = letter.upper()
            if key in self.buttons:
                color = THEME["ok"] if key in p.get("masked_word", "").upper() else THEME["bad"]
                self._disable_key(key, color, "#FFFFFF")

        self._set_new_game_enabled(status not in ("EN_ATTENTE", "EN_COURS"))
        if status == "TERMINE":
            self._duel_id = None


def main() -> None:
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    HangmanApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()