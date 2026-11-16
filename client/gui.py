import os
import queue
import sys
import threading
import time
from datetime import datetime
from string import ascii_uppercase
import tkinter as tk
from tkinter import messagebox
from typing import Any, Callable

# S'assure que la racine du projet et le dossier temporaire PyInstaller sont dans sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if hasattr(sys, "_MEIPASS") and sys._MEIPASS not in sys.path:
    sys.path.insert(0, sys._MEIPASS)

import customtkinter as ctk

from client.connection import GameClient
from client.controller import GameController
from protocol.discovery import discover_servers
from protocol.message import Message

# Résolution des bibliothèques Tcl/Tk sous Windows si nécessaire
if "TCL_LIBRARY" not in os.environ:
    _tcl = os.path.join(sys.prefix, "tcl", "tcl8.6")
    if os.path.exists(_tcl):
        os.environ["TCL_LIBRARY"] = _tcl
if "TK_LIBRARY" not in os.environ:
    _tk = os.path.join(sys.prefix, "tcl", "tk8.6")
    if os.path.exists(_tk):
        os.environ["TK_LIBRARY"] = _tk

END_MESSAGES = {
    "GAGNE": "🎉 Félicitations ! Vous avez trouvé le mot !",
    "PERDU": "💀 Dommage, vous avez épuisé tous vos essais...",
    "ABANDONNE": "Partie abandonnée.",
}

# Palette unique (mode sombre)
THEME = {
    "bg_card": "#181C24",
    "bg_elevated": "#222734",
    "bg_hover": "#2D3446",
    "border": "#2D3444",
    "text_primary": "#F8FAFC",
    "text_secondary": "#94A3B8",
    "text_muted": "#5A6578",
    "accent_primary": "#38BDF8",
    "accent_success": "#00E676",
    "accent_success_bg": "#0E4D2B",
    "accent_danger": "#FF5252",
    "accent_danger_bg": "#4A191F",
    "accent_warning": "#F59E0B",
}

DANGER_BTN = ("#DC2626", "#B91C1C")

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

KEYBOARD_ROWS = [
    ascii_uppercase[:9],    # A - I
    ascii_uppercase[9:18],  # J - R
    ascii_uppercase[18:],   # S - Z
]

LOG_COLORS = {
    "ENVOI": "#38BDF8",
    "REÇU": "#00E676",
    "CONNEXION": "#A78BFA",
    "RECONNEXION": "#F59E0B",
    "ERREUR": "#FF5252",
    "INFO": "#94A3B8",
}


# --- Helpers de construction des widgets ---

def _font(size: int, bold: bool = False, family: str | None = None) -> ctk.CTkFont:
    options: dict[str, Any] = {"size": size, "weight": "bold" if bold else "normal"}
    if family:
        options["family"] = family
    return ctk.CTkFont(**options)


def _packed(widget: Any, **pack_opts: Any) -> Any:
    """Pack le widget et le renvoie, pour pouvoir l'affecter directement."""
    widget.pack(**pack_opts)
    return widget


def _label(
    parent: Any,
    text: str | None = None,
    size: int = 12,
    bold: bool = False,
    color: str | None = None,
    family: str | None = None,
    **kw: Any,
) -> ctk.CTkLabel:
    if text is not None:
        kw["text"] = text
    return ctk.CTkLabel(parent, font=_font(size, bold, family), text_color=color or THEME["text_primary"], **kw)


def _button(
    parent: Any,
    text: str,
    command: Callable[[], Any],
    fg: str,
    hover: str,
    txt: str | None = None,
    size: int = 12,
    bold: bool = False,
    **kw: Any,
) -> ctk.CTkButton:
    kw.setdefault("height", 32)
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        fg_color=fg,
        hover_color=hover,
        text_color=txt or THEME["text_primary"],
        font=_font(size, bold),
        **kw,
    )


def _badge(parent: Any, var: tk.StringVar, color: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        parent,
        textvariable=var,
        font=_font(12, bold=True),
        text_color=color,
        fg_color=THEME["bg_elevated"],
        corner_radius=8,
        padx=12,
        pady=4,
    )


def _card(parent: Any, **pack_opts: Any) -> ctk.CTkFrame:
    frame = ctk.CTkFrame(
        parent,
        corner_radius=12,
        fg_color=THEME["bg_card"],
        border_width=1,
        border_color=THEME["border"],
    )
    return _packed(frame, **pack_opts)


def _labeled_entry(parent: Any, label: str, var: tk.StringVar, width: int) -> ctk.CTkEntry:
    _label(parent, label, color=THEME["text_secondary"]).pack(side="left", padx=(0, 4))
    entry = ctk.CTkEntry(parent, textvariable=var, width=width, height=28, font=_font(12))
    entry.pack(side="left", padx=(0, 10))
    return entry

CATEGORIES_MENU = {
    "🎲 Aléatoire": None,
    "1. L'école & l'instruction": 1,
    "2. Paysages & climat": 2,
    "3. Qualités & défauts": 3,
    "4. Calcul & mesures": 4,
    "5. Aliments & boissons": 5,
    "6. Le corps humain": 6,
    "7. Sens & volonté": 7,
    "8. Intérieur & mobilier": 8,
    "9. Industrie & travail": 9,
    "10. Les arts": 10,
    "11. L'agriculture": 11,
    "12. Bois, chasse & pêche": 12,
    "13. Gestes & mouvements": 13,
    "14. Époque & saisons": 14,
    "15. Vêtements & toilette": 15,
    "16. Sports & jeux": 16,
    "17. Maison & bâtiment": 17,
    "18. Les voyages": 18,
    "19. Les animaux": 19,
    "20. Ville & univers": 20,
    "21. Minéraux & végétaux": 21,
    "22. Le commerce": 22,
    "23. La communication": 23,
    "24. Joies & peines": 24,
    "25. Gouvernement & justice": 25,
    "26. L'armée": 26,
    "27. Vie & hygiène": 27,
}


class HangmanApp:
    def __init__(self, root: ctk.CTk | tk.Tk | None = None, client: GameClient | None = None) -> None:
        if root is None:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
            root = ctk.CTk()
        self.root = root

        self.client = client or GameClient("127.0.0.1", 8888)
        self.controller = GameController(self.client)
        self._is_busy = False
        self._gui_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._timer_started_at: float | None = None
        self._timer_after_id: str | None = None
        self.current_room_id: str | None = None
        self.chat_history: list[dict[str, Any]] = []

        self.root.title("🎯 Pendu Réseau M1 — Client")
        self.root.geometry("1080x830")
        self.root.minsize(960, 740)

        self.client.log_callback = self.log_network_event

        self._init_vars()
        self._build_ui()
        self._bind_events()

        self._check_saved_session()
        if self.client.is_connected():
            self._mark_connected()
        else:
            self._set_status("Déconnecté", THEME["accent_danger"])

        self.root.after(30, self._process_gui_queue)
        self.root.after(200, self._refresh)

    # --- INITIALISATION ---

    def _init_vars(self) -> None:
        self.host_var = tk.StringVar(value=self.client.host or "127.0.0.1")
        self.port_var = tk.StringVar(value=str(self.client.port or 8888))
        self.tls_var = tk.BooleanVar(value=False)
        self.pseudo_var = tk.StringVar(value=self.client.player_name or "Joueur")

        self.word_var = tk.StringVar(value="_ _ _ _ _")
        self.timer_var = tk.StringVar(value="Temps : 00:00")
        self.info_var = tk.StringVar(value="Essais restants : 6 / 6")
        self.lives_var = tk.StringVar(value="❤️ 6 / 6")
        self.errors_var = tk.StringVar(value="💀 0 / 6")
        self.feedback_var = tk.StringVar(value="Bienvenue ! Connectez-vous et lancez une manche.")
        self.hangman_var = tk.StringVar(value=HANGMAN_STAGES[0])
        self.room_badge_var = tk.StringVar(value="🏠 Salon : aucun")

    def _build_ui(self) -> None:
        container = ctk.CTkFrame(self.root, corner_radius=0, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=16, pady=12)

        self._build_header(container)

        self.tabview = ctk.CTkTabview(container, corner_radius=14)
        self.tabview.pack(fill="both", expand=True, pady=(6, 0))
        self._build_game_tab(self.tabview.add("🎮 Plateau de Jeu"))
        self._build_chat_tab(self.tabview.add("💬 Chat en Direct"))
        self._build_inspector_tab(self.tabview.add("🔍 Inspecteur Réseau"))

    def _bind_events(self) -> None:
        self.root.bind("<Key>", self._on_key_press)
        for entry in (self.host_entry, self.port_entry, self.pseudo_entry):
            entry.bind("<Return>", lambda _: self.connect_or_disconnect())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- BANDEAU SUPÉRIEUR ---

    def _build_header(self, parent: Any) -> None:
        card = _card(parent, fill="x", pady=(0, 6), padx=2)

        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=(10, 6))
        _label(row1, "🎮 PENDU RÉSEAU", size=18, bold=True, color=THEME["accent_primary"]).pack(side="left")

        status_box = ctk.CTkFrame(row1, fg_color="transparent")
        status_box.pack(side="right")
        self.status_canvas = tk.Canvas(status_box, width=14, height=14, highlightthickness=0, bg=THEME["bg_card"])
        self.status_circle = self.status_canvas.create_oval(2, 2, 12, 12, fill=THEME["accent_danger"], outline="")
        self.status_canvas.pack(side="left", padx=(0, 6))
        self.status_label = _packed(_label(status_box, "Déconnecté", bold=True), side="left", padx=(0, 10))
        self.session_info_label = _packed(
            _label(status_box, "", size=11, color=THEME["accent_primary"], family="Consolas"), side="left"
        )

        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(fill="x", padx=14, pady=(0, 10))

        self.tls_check = ctk.CTkCheckBox(form, text="TLS", variable=self.tls_var, width=60, font=_font(12))
        self.tls_check.pack(side="left", padx=(0, 8))

        self.host_entry = _labeled_entry(form, "Hôte :", self.host_var, 120)
        self.port_entry = _labeled_entry(form, "Port :", self.port_var, 70)
        self.pseudo_entry = _labeled_entry(form, "Pseudo :", self.pseudo_var, 100)

        self.connect_btn = _packed(
            _button(form, "🔌 Connexion", self.connect_or_disconnect,
                    THEME["accent_primary"], "#0284C7", size=12, bold=True, height=28),
            side="left", padx=(0, 8),
        )
        self.resume_btn = _packed(
            _button(form, "🔄 Reprendre session", self.resume_existing_session,
                    THEME["bg_elevated"], THEME["bg_hover"], THEME["text_primary"], height=28),
            side="left", padx=(0, 8),
        )
        self.discover_btn = _packed(
            _button(form, "🔍 Découvrir", self.discover_local_servers,
                    THEME["bg_elevated"], THEME["bg_hover"], THEME["accent_primary"], bold=True, height=28, width=90),
            side="left", padx=(0, 12),
        )
        _packed(
            _label(form, bold=True, color=THEME["accent_warning"], textvariable=self.room_badge_var),
            side="right",
        )

    # --- ONGLET 1 : JEU ---

    def _build_game_tab(self, parent: Any) -> None:
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(8, 4))

        hangman_card = _card(top, side="left", padx=(0, 10), pady=4)
        _label(hangman_card, textvariable=self.hangman_var, size=14, family="Consolas", justify="left").pack(
            padx=16, pady=12
        )

        info_card = _card(top, side="right", fill="both", expand=True, pady=4)
        _label(info_card, textvariable=self.word_var, size=34, bold=True, family="Consolas").pack(pady=(16, 10))

        badges = ctk.CTkFrame(info_card, fg_color="transparent")
        badges.pack(pady=(0, 8))
        for var, color in (
            (self.timer_var, THEME["accent_primary"]),
            (self.lives_var, THEME["accent_success"]),
            (self.errors_var, THEME["accent_danger"]),
        ):
            _badge(badges, var, color).pack(side="left", padx=4)

        self.feedback_label = _packed(
            _label(info_card, textvariable=self.feedback_var, color=THEME["text_secondary"]), pady=(0, 10)
        )

        # Clavier virtuel
        keyboard = _card(parent, fill="x", padx=12, pady=(4, 6))
        _label(
            keyboard,
            "CLAVIER VIRTUEL (CLIQUEZ OU TAPEZ SUR VOTRE CLAVIER PHYSIQUE)",
            size=10, bold=True, color=THEME["text_secondary"],
        ).pack(pady=(6, 4))

        self.buttons: dict[str, ctk.CTkButton] = {}
        for row in KEYBOARD_ROWS:
            line = ctk.CTkFrame(keyboard, fg_color="transparent")
            line.pack(pady=2)
            for letter in row:
                self.buttons[letter] = _packed(
                    _button(
                        line, letter, lambda l=letter: self.play(l),
                        THEME["bg_elevated"], THEME["bg_hover"], THEME["text_primary"],
                        size=13, bold=True, width=42, height=36, corner_radius=8,
                    ),
                    side="left", padx=3,
                )

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(pady=6)

        self.category_var = ctk.StringVar(value="🎲 Aléatoire")
        self.category_menu = ctk.CTkOptionMenu(
            actions,
            variable=self.category_var,
            values=list(CATEGORIES_MENU.keys()),
            width=200,
            height=34,
            fg_color=THEME["bg_elevated"],
            button_color=THEME["border"],
            button_hover_color=THEME["bg_hover"],
            dropdown_font=ctk.CTkFont(size=11),
        )
        self.category_menu.pack(side="left", padx=6)

        self.new_game_btn = _packed(
            _button(actions, "✨ Nouvelle Manche", self.start_new_game,
                    THEME["accent_success"], "#15803D", "#052410", bold=True, height=34),
            side="left", padx=6,
        )
        self.quit_btn = _packed(
            _button(actions, "🚪 Abandonner", self.quit_game,
                    THEME["accent_danger"], "#991B1B", "white", height=34),
            side="left", padx=6,
        )
        self.disconnect_sim_btn = _packed(
            _button(actions, "⚡ Coupure simulée (Idempotence)", self.simulate_disconnect,
                    THEME["bg_elevated"], THEME["bg_hover"], THEME["accent_warning"], height=34),
            side="left", padx=6,
        )

    # --- ONGLET 2 : CHAT ET SALONS ---

    def _build_chat_tab(self, parent: Any) -> None:
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(8, 4))
        _label(top, "💬 Discussion en direct avec les joueurs", size=14, bold=True).pack(side="left")

        self.chat_scope_seg = ctk.CTkSegmentedButton(
            top,
            values=["Salon Courant", "Chat Global"],
            command=self._on_chat_scope_change,
        )
        self.chat_scope_seg.set("Salon Courant")
        self.chat_scope_seg.pack(side="right")

        self.chat_messages_frame = ctk.CTkScrollableFrame(
            parent,
            corner_radius=12,
            fg_color=THEME["bg_card"],
            border_width=1,
            border_color=THEME["border"],
            height=380,
        )
        self.chat_messages_frame.pack(fill="both", expand=True, padx=14, pady=4)

        input_bar = ctk.CTkFrame(parent, fg_color="transparent")
        input_bar.pack(fill="x", padx=14, pady=(6, 10))
        self.chat_entry = ctk.CTkEntry(
            input_bar,
            placeholder_text="Écrivez votre message... (Appuyez sur Entrée pour envoyer)",
            height=36,
            font=_font(12),
        )
        self.chat_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.chat_entry.bind("<Return>", lambda _: self._send_chat_message())
        self.chat_send_btn = _packed(
            _button(input_bar, "Envoyer 🚀", self._send_chat_message,
                    THEME["accent_primary"], "#0284C7", bold=True, height=36, width=100),
            side="right",
        )

        room_bar = ctk.CTkFrame(parent, fg_color="transparent")
        room_bar.pack(fill="x", padx=14, pady=(0, 10))
        self.room_entry = ctk.CTkEntry(
            room_bar,
            placeholder_text="Nom du salon (1 à 20 caractères)",
            height=32,
            width=260,
        )
        self.room_entry.pack(side="left", padx=(0, 8))
        _packed(
            _button(room_bar, "➡️ Rejoindre", self._join_room_from_entry,
                    THEME["accent_primary"], "#0284C7", height=32, width=110),
            side="left", padx=(0, 8),
        )
        _packed(
            _button(room_bar, "🚪 Quitter le salon", self._leave_room_action,
                    THEME["accent_danger"], "#991B1B", height=32, width=150),
            side="left",
        )

        self._refresh_chat_display()

    def _on_chat_scope_change(self, value: str) -> None:
        self._refresh_chat_display()

    def _visible_messages(self) -> list[dict[str, Any]]:
        """Renvoie les messages à afficher selon la portée choisie."""
        if self.chat_scope_seg.get() == "Chat Global":
            return [m for m in self.chat_history if m["scope"] == "global"]
        return [
            m for m in self.chat_history
            if m["scope"] == "room" and m["room_id"] == self.current_room_id
        ]

    def _refresh_chat_display(self) -> None:
        for widget in self.chat_messages_frame.winfo_children():
            widget.destroy()

        for msg in self._visible_messages():
            bubble = ctk.CTkFrame(self.chat_messages_frame, corner_radius=10, fg_color=THEME["bg_elevated"])
            bubble.pack(fill="x", padx=6, pady=3)

            if msg["sender"] == "Système":
                color = THEME["accent_warning"]
            elif msg["sender"] == self.pseudo_var.get():
                color = THEME["accent_success"]
            else:
                color = THEME["accent_primary"]

            head = ctk.CTkFrame(bubble, fg_color="transparent")
            head.pack(fill="x", padx=8, pady=(4, 0))
            scope = "Salon" if msg["scope"] == "room" else "Global"
            _label(head, msg["sender"], size=11, bold=True, color=color).pack(side="left")
            _label(head, f"[{msg.get('time', '')}] • {scope}", size=9, color=THEME["text_muted"]).pack(side="right")
            _label(
                bubble, msg["text"], wraplength=760, justify="left",
            ).pack(anchor="w", padx=8, pady=(2, 6))

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
        resp = self._checked(self.controller.chat, text, scope, title="Chat", default="Message refusé.")
        if resp is None:
            return
        self.chat_entry.delete(0, "end")
        self._add_chat_line(resp.payload)  # l'expéditeur ne reçoit pas son propre push

    def _join_room_from_entry(self) -> None:
        name = self.room_entry.get().strip()
        if not name:
            return
        resp = self._checked(self.controller.join_room, name, title="Salon",
                             default="Impossible de rejoindre le salon.")
        if resp is None:
            return
        self.room_entry.delete(0, "end")
        self._set_room(resp.payload.get("room_id"))

    def _leave_room_action(self) -> None:
        resp = self._checked(self.controller.leave_room, title="Salon",
                             default="Impossible de quitter le salon.")
        if resp is not None:
            self._set_room(None)

    def _set_room(self, room_id: str | None) -> None:
        self.current_room_id = room_id
        self.room_badge_var.set(f"🏠 Salon : {room_id or 'aucun'}")
        self._refresh_chat_display()

    # --- ONGLET 3 : INSPECTEUR RÉSEAU ---

    def _build_inspector_tab(self, parent: Any) -> None:
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(8, 4))
        _label(top, "🔍 Trames JSON TCP délimitées par \\n", size=14, bold=True).pack(side="left")
        _packed(
            _button(top, "🗑 Effacer les logs", self._clear_logs,
                    THEME["bg_elevated"], THEME["bg_hover"], THEME["text_primary"],
                    size=11, width=120, height=28),
            side="right",
        )

        self.log_text = ctk.CTkTextbox(parent, corner_radius=12, font=_font(12, family="Consolas"), wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=14, pady=(4, 10))
        for tag, color in LOG_COLORS.items():
            self.log_text.tag_config(tag, foreground=color)

    def _insert_log(self, direction: str, text: str) -> None:
        tag = direction if direction in LOG_COLORS else None
        self.log_text.insert("end", f"[{direction}] ", tag)
        self.log_text.insert("end", f"{text}\n")
        self.log_text.see("end")

    def _clear_logs(self) -> None:
        self.log_text.delete("1.0", "end")

    def log_network_event(self, direction: str, text: str) -> None:
        """Point d'entrée pour les logs de GameClient (thread-safe via la file)."""
        self._gui_queue.put(("LOG", (direction, text)))

    # --- POTENCE EN TEXTE ---

    def _show_hangman(self, errors_made: int, status: str | None = None) -> None:
        stage = min(errors_made, len(HANGMAN_STAGES) - 1)
        text = HANGMAN_STAGES[stage]
        if status == "GAGNE":
            text += "\n   Gagné !"
        self.hangman_var.set(text)

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
        elapsed = time.monotonic() - self._timer_started_at
        self._timer_started_at = None
        if self._timer_after_id is not None:
            self.root.after_cancel(self._timer_after_id)
            self._timer_after_id = None
        formatted = self._format_elapsed(elapsed)
        self.timer_var.set(f"Temps : {formatted}")
        return formatted

    # --- APPELS RÉSEAU ---

    def _call(
        self,
        action: Callable[..., Message],
        *args: Any,
        title: str = "Erreur réseau",
        **kwargs: Any,
    ) -> Message | None:
        """Appelle le contrôleur. En cas de coupure, affiche l'erreur et renvoie None."""
        try:
            return action(*args, **kwargs)
        except (ConnectionError, OSError) as exc:
            self._set_status("Déconnecté", THEME["accent_danger"])
            messagebox.showerror(title, str(exc))
            return None

    def _checked(
        self,
        action: Callable[..., Message],
        *args: Any,
        title: str,
        default: str = "Requête refusée.",
        **kwargs: Any,
    ) -> Message | None:
        """Comme _call, mais renvoie None aussi si le serveur répond ERROR (avec un avertissement)."""
        resp = self._call(action, *args, title=title, **kwargs)
        if resp is None:
            return None
        if resp.type == "ERROR":
            messagebox.showwarning(title, resp.payload.get("message", default))
            return None
        return resp

    def _run_async(
        self,
        task: Callable[..., Any],
        args: tuple = (),
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Exécute une opération en arrière-plan. Réservé à la découverte UDP."""
        if self._is_busy:
            return
        self._is_busy = True

        def worker() -> None:
            try:
                res = task(*args)
                self._gui_queue.put(("CALLBACK", (self._release_busy, ())))
                if on_success:
                    self._gui_queue.put(("CALLBACK", (on_success, (res,))))
            except Exception as exc:
                self._gui_queue.put(("CALLBACK", (self._release_busy, ())))
                if on_error:
                    self._gui_queue.put(("CALLBACK", (on_error, (exc,))))
                else:
                    self._gui_queue.put(("LOG", ("ERREUR", str(exc))))
                    self._gui_queue.put(("ERROR_ALERT", ("Erreur Réseau", str(exc))))

        threading.Thread(target=worker, daemon=True).start()

    def _release_busy(self) -> None:
        self._is_busy = False

    def _process_gui_queue(self) -> None:
        """Traite les logs et les callbacks sur le thread principal de Tkinter."""
        try:
            while not self._gui_queue.empty():
                msg_type, payload = self._gui_queue.get_nowait()
                if msg_type == "LOG":
                    direction, text = payload
                    self._insert_log(direction, text)
                elif msg_type == "CALLBACK":
                    func, args = payload
                    func(*args)
                elif msg_type == "ERROR_ALERT":
                    title, msg = payload
                    messagebox.showerror(title, msg)
        finally:
            self.root.after(30, self._process_gui_queue)

    def _refresh(self) -> None:
        """Relit le réseau sans bloquer, affiche les messages reçus, puis se reprogramme."""
        try:
            messages = self.controller.poll()
        except (ConnectionError, OSError):
            self.client.close()
            self._set_status("Déconnecté", THEME["accent_danger"])
            messages = []
        for m in messages:
            self._add_chat_line(m)
        self.root.after(200, self._refresh)

    # --- AFFICHAGE : STATUT, FEEDBACK, CLAVIER ---

    def _set_status(self, text: str, color: str) -> None:
        self.status_canvas.itemconfig(self.status_circle, fill=color)
        self.status_label.configure(text=text)

    def _set_feedback(self, text: str, color: str | None = None) -> None:
        self.feedback_var.set(text)
        self.feedback_label.configure(text_color=color or THEME["text_secondary"])

    def _mark_connected(self) -> None:
        self._set_status(f"Connecté à {self.client.host}:{self.client.port}", THEME["accent_success"])
        self.connect_btn.configure(text="🔴 Déconnecter", fg_color=DANGER_BTN)
        session_short = (self.client.session_id or "")[:8]
        self.session_info_label.configure(
            text=f"Session : {session_short}... | Joueur : {self.client.player_name}"
        )

    def _reset_connect_button(self) -> None:
        self.connect_btn.configure(state="normal", text="🔌 Connexion", fg_color=THEME["accent_primary"])

    def _reset_keyboard(self) -> None:
        for btn in self.buttons.values():
            btn.configure(state="normal", fg_color=THEME["bg_elevated"], text_color=THEME["text_primary"])

    def _disable_key(self, letter: str, bg: str, fg: str) -> None:
        self.buttons[letter].configure(state="disabled", fg_color=bg, text_color=fg)

    def _disable_all_keys(self) -> None:
        for btn in self.buttons.values():
            btn.configure(state="disabled")

    def _on_key_press(self, event: tk.Event) -> None:
        """Capture la saisie physique des lettres A-Z pour jouer."""
        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, tk.Text)) or "entry" in str(focused).lower():
            return
        char = (event.char or "").upper()
        if char in self.buttons and self.buttons[char].cget("state") == "normal":
            self.play(char)

    def _read_port(self) -> int | None:
        try:
            return int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("Port invalide", "Veuillez entrer un numéro de port valide (ex: 8888).")
            return None

    def _check_saved_session(self) -> None:
        """Active le bouton de reprise si un session.json est disponible."""
        if os.path.exists("session.json") and self.client.load_session("session.json"):
            self.resume_btn.configure(state="normal", text_color=THEME["accent_primary"])
            self.session_info_label.configure(text=f"Session détectée ({self.client.player_name})")
            return
        self.resume_btn.configure(state="disabled", text_color=THEME["text_muted"])

    # --- CONNEXION, REPRISE ---

    def connect_or_disconnect(self) -> None:
        if self.client.is_connected():
            self.client.close()
            self._set_status("Déconnecté", THEME["accent_danger"])
            self._reset_connect_button()
            self._set_feedback("Connexion fermée.")
            return

        host = self.host_var.get().strip() or "127.0.0.1"
        port = self._read_port()
        if port is None:
            return
        pseudo = self.pseudo_var.get().strip() or "Joueur"

        self._set_status("Connexion en cours...", THEME["accent_warning"])
        self.connect_btn.configure(state="disabled")

        try:
            welcome = self.controller.connect(host, port, pseudo)
        except (ConnectionError, OSError) as exc:
            self._reset_connect_button()
            self._set_status("Échec connexion", THEME["accent_danger"])
            self._set_feedback(f"Erreur de connexion : {exc}", THEME["accent_danger"])
            messagebox.showerror("Connexion impossible", f"Impossible d'ouvrir la socket vers {host}:{port} :\n{exc}")
            return

        self.connect_btn.configure(state="normal")
        if welcome.type != "WELCOME":
            self._set_status("Erreur session", THEME["accent_danger"])
            messagebox.showerror("Erreur d'accueil", welcome.payload.get("message", "Échec HELLO"))
            return

        self._mark_connected()
        self.client.save_session("session.json")
        self._check_saved_session()
        self._set_feedback(f"Bienvenue {self.client.player_name} ! Lancement de la partie...", THEME["accent_success"])
        self.start_new_game()

    def resume_existing_session(self) -> None:
        if not self.client.session_id and not self.client.load_session("session.json"):
            messagebox.showinfo("Aucune session", "Aucune session enregistrée à reprendre.")
            return

        host = self.host_var.get().strip() or "127.0.0.1"
        port = self._read_port()
        if port is None:
            return

        self._set_status("Reprise de session...", THEME["accent_warning"])
        try:
            resp = self.controller.resume(host, port)
        except (ConnectionError, OSError) as exc:
            self._set_status("Déconnecté", THEME["accent_danger"])
            messagebox.showwarning("Reprise impossible", f"Erreur de reprise : {exc}")
            return

        if resp.type != "STATE":
            messagebox.showwarning("Reprise impossible", resp.payload.get("message", "Session expirée"))
            self._set_status("Session expirée", THEME["accent_danger"])
            return

        self._mark_connected()
        self._set_feedback("Session restaurée avec succès !", THEME["accent_success"])
        if resp.payload.get("status") == "IDLE":
            self.start_new_game()
        else:
            self.update_from_state(resp)

    # --- DÉCOUVERTE UDP ---

    def discover_local_servers(self) -> None:
        self._set_status("Recherche de serveurs...", THEME["accent_warning"])
        self._set_feedback("Sondage UDP du réseau local en cours...")
        self.discover_btn.configure(state="disabled", text="🔍 Recherche...")

        def finish() -> None:
            self.discover_btn.configure(state="normal", text="🔍 Découvrir")

        def on_success(servers: list[dict[str, Any]]) -> None:
            finish()
            if not servers:
                self._set_status("Aucun serveur trouvé", THEME["text_secondary"])
                self._set_feedback("Aucun serveur de Pendu détecté sur le réseau local.")
                messagebox.showinfo(
                    "Découverte réseau",
                    "Aucun serveur de Pendu n'a répondu à la sonde UDP sur le réseau local.\n\n"
                    "Vérifiez que le serveur est bien démarré sur la machine distante ou locale.",
                )
            elif len(servers) == 1:
                s = servers[0]
                self._apply_server(s)
                messagebox.showinfo(
                    "Serveur détecté",
                    f"Serveur trouvé avec succès !\n\n"
                    f"• Nom : {s['server_name']}\n"
                    f"• Adresse : {s['ip']}:{s['port']}\n"
                    f"• Joueurs connectés : {s['players_count']}\n"
                    f"• Sécurité TLS : {'Oui 🔒' if s.get('use_tls') else 'Non'}\n\n"
                    "Les champs Hôte et Port ont été pré-remplis automatiquement.",
                )
            else:
                self._show_server_picker_dialog(servers)

        def on_error(exc: Exception) -> None:
            finish()
            self._set_status("Erreur découverte", THEME["accent_danger"])
            self._set_feedback(f"Échec de la sonde : {exc}", THEME["accent_danger"])

        self._run_async(lambda: discover_servers(timeout=1.2), on_success=on_success, on_error=on_error)

    def _apply_server(self, s: dict[str, Any]) -> None:
        """Remplit Hôte, Port et TLS avec un serveur découvert."""
        self.host_var.set(s["ip"])
        self.port_var.set(str(s["port"]))
        self.tls_var.set(bool(s.get("use_tls", False)))
        self._set_status(f"Serveur sélectionné ({s['ip']})", THEME["accent_success"])
        self._set_feedback(f"Serveur sélectionné : {s['server_name']} ({s['ip']}:{s['port']})", THEME["accent_success"])

    def _show_server_picker_dialog(self, servers: list[dict[str, Any]]) -> None:
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Serveurs détectés sur le réseau")
        dialog.geometry("520x340")
        dialog.transient(self.root)
        dialog.grab_set()

        _label(
            dialog, f"🌐 {len(servers)} serveurs de Pendu détectés :",
            size=14, bold=True, color=THEME["accent_primary"],
        ).pack(padx=16, pady=(16, 8), anchor="w")

        scroll = ctk.CTkScrollableFrame(dialog, height=200)
        scroll.pack(fill="both", expand=True, padx=16, pady=8)

        for s in servers:
            card = ctk.CTkFrame(scroll, fg_color=THEME["bg_elevated"], corner_radius=8)
            card.pack(fill="x", pady=4, padx=4)

            info = ctk.CTkFrame(card, fg_color="transparent")
            info.pack(side="left", padx=10, pady=8)
            _label(info, s["server_name"], bold=True).pack(anchor="w")
            tls = " • TLS 🔒" if s.get("use_tls") else ""
            _label(
                info, f"{s['ip']}:{s['port']} • {s['players_count']} joueur(s){tls}",
                size=11, color=THEME["text_secondary"],
            ).pack(anchor="w")

            def choose(srv: dict[str, Any] = s) -> None:
                self._apply_server(srv)
                dialog.destroy()

            _button(
                card, "Sélectionner", choose,
                THEME["accent_primary"], "#0284C7", height=28, width=90,
            ).pack(side="right", padx=10, pady=8)

    # --- PARTIE ---

    def start_new_game(self) -> None:
        if not self.client.is_connected() or not self.client.session_id:
            self.connect_or_disconnect()
            return

        self._reset_keyboard()
        self._set_feedback("Démarrage d'une nouvelle manche...")
        selected_label = self.category_var.get()
        cat_id = CATEGORIES_MENU.get(selected_label)
        resp = self._call(self.controller.new_game, category_id=cat_id, title="Erreur")
        if resp is None:
            return
        self.update_from_state(resp)
        theme = resp.payload.get("category", "")
        theme_msg = f" [Thème : {theme}]" if theme else ""
        self._set_feedback(f"Nouvelle manche commencée{theme_msg} ! Choisissez une lettre.", THEME["accent_primary"])

    def play(self, letter: str) -> None:
        letter = letter.upper()
        resp = self._call(self.controller.guess, letter, title="Erreur Réseau")
        if resp is None:
            return
        # Une lettre refusée (ERROR) n'est pas grisée : update_from_state affiche l'erreur
        if resp.type != "ERROR" and letter in self.buttons:
            self._disable_key(letter, THEME["bg_card"], THEME["text_muted"])
        self.update_from_state(resp)

    def quit_game(self) -> None:
        if not messagebox.askyesno("Abandonner", "Voulez-vous vraiment abandonner la partie ?"):
            return
        if self._call(self.controller.quit_game, title="Attention") is None:
            return

        self._stop_timer()
        self._set_status("Session clôturée", THEME["text_secondary"])
        self.info_var.set("Session clôturée.")
        self.feedback_var.set("Partie abandonnée.")
        self._set_room(None)
        self._disable_all_keys()

    def simulate_disconnect(self) -> None:
        """Ferme la socket locale pour démontrer la reprise (RESUME)."""
        self.client.close()
        self._set_status("Socket coupée (Simulation)", THEME["accent_warning"])
        self._set_feedback(
            "Coupure simulée : cliquez sur une lettre pour tester le rejeu idempotent !",
            THEME["accent_warning"],
        )
        messagebox.showinfo(
            "Coupure simulée",
            "La socket TCP locale a été fermée.\n\n"
            "Cliquez sur une lettre ou une action :\n"
            "Le client détectera la coupure, se reconnectera automatiquement, "
            "enverra RESUME et rejouera votre requête avec idempotence !",
        )

    def update_from_state(self, resp: Any) -> None:
        """Met à jour l'affichage avec le payload STATE."""
        if resp.type == "ERROR":
            messagebox.showwarning("Erreur Applicative", f"{resp.payload.get('code')} : {resp.payload.get('message')}")
            return

        p = resp.payload
        max_errors = p.get("max_errors", 6)
        masked = p.get("masked_word", "")
        self.word_var.set("  ".join(masked.replace(" ", "")))

        errors_left = p.get("errors_left", max_errors)
        errors_made = max(0, max_errors - errors_left)
        theme = p.get("category", "")
        theme_str = f"  •  Thème : {theme}" if theme else ""
        self.info_var.set(f"Essais restants : {errors_left} / {max_errors}  (Erreurs : {errors_made}){theme_str}")
        self.lives_var.set(f"❤️ {errors_left} / {max_errors}")
        self.errors_var.set(f"💀 {errors_made} / {max_errors}")

        status = p.get("status")
        self._show_hangman(errors_made, status=status)

        for letter in p.get("used_letters", []):
            key = letter.upper()
            if key not in self.buttons:
                continue
            if key in masked:
                self._disable_key(key, THEME["accent_success_bg"], THEME["accent_success"])
            else:
                self._disable_key(key, THEME["accent_danger_bg"], THEME["accent_danger"])

        if status == "EN_COURS":
            if self._timer_started_at is None:
                self._start_timer()
            self._set_feedback(f"Partie en cours. Erreurs : {errors_made}/{max_errors}")
        elif status in ("GAGNE", "PERDU", "ABANDONNE"):
            self._end_game(p, status)

    def _end_game(self, p: dict[str, Any], status: str) -> None:
        elapsed = self._stop_timer()
        self._disable_all_keys()

        secret = p.get("secret_word")
        msg = END_MESSAGES.get(status, f"Partie finie : {status}")
        if elapsed is not None:
            msg += f"\n\n⏱ Temps écoulé : {elapsed}"
        if status == "PERDU" and secret:
            msg += f"\n\n📖 Le mot était : {secret}"
            self._set_feedback(f"Défaite ! Le mot était {secret}.", THEME["accent_danger"])
        elif status == "GAGNE":
            self._set_feedback("Victoire ! Vous avez trouvé le mot !", THEME["accent_success"])

        messagebox.showinfo("Fin de partie", msg)

    # --- FERMETURE ---

    def _on_close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
        self.root.destroy()


def main() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    app = HangmanApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()