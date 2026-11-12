import os
import sys
import queue
import threading
import time
from datetime import datetime
from string import ascii_uppercase
import tkinter as tk
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk

from client.connection import GameClient
from protocol.message import Message
from protocol.discovery import discover_servers

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

# Palette CustomTkinter Bivalente (Mode Clair, Mode Sombre)
THEME = {
    "bg_base": ("#F1F5F9", "#0F1218"),
    "bg_card": ("#FFFFFF", "#181C24"),
    "bg_elevated": ("#E2E8F0", "#222734"),
    "bg_hover": ("#CBD5E1", "#2D3446"),
    "border": ("#CBD5E1", "#2D3444"),
    "text_primary": ("#0F172A", "#F8FAFC"),
    "text_secondary": ("#64748B", "#94A3B8"),
    "text_muted": ("#94A3B8", "#5A6578"),
    "accent_primary": ("#0284C7", "#38BDF8"),
    "accent_success": ("#16A34A", "#00E676"),
    "accent_success_bg": ("#DCFCE7", "#0E4D2B"),
    "accent_danger": ("#DC2626", "#FF5252"),
    "accent_danger_bg": ("#FEE2E2", "#4A191F"),
    "accent_warning": ("#D97706", "#F59E0B"),
}


class LetterButton(ctk.CTkButton):
    """
    Bouton CustomTkinter avec rétro-compatibilité totale pour l'accès aux états :
    btn['state'], btn.cget('state') et btn.configure(state=...).
    """
    def __getitem__(self, item: str) -> Any:
        if item == "state":
            return self._state
        if item in ("bg", "fg_color"):
            return self._fg_color
        try:
            return super().__getitem__(item)
        except Exception:
            return getattr(self, f"_{item}", None)

    def cget(self, attribute_name: str) -> Any:
        if attribute_name == "state":
            return self._state
        return super().cget(attribute_name)


class HangmanApp:
    def __init__(self, root: ctk.CTk | tk.Tk | None = None, client: GameClient | None = None) -> None:
        if root is None:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
            self.root = ctk.CTk()
            self._owns_root = True
        else:
            self.root = root
            self._owns_root = False

        self.client = client or GameClient("127.0.0.1", 8888)
        self._timer_started_at: float | None = None
        self._timer_after_id: str | None = None
        self._gui_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.inspector_visible: bool = True

        self._current_errors: int = 0
        self._current_status: str | None = None
        self.current_room_id: str | None = None
        self.current_room_name: str | None = None

        self.root.title("🎯 Pendu Réseau M1 — CustomTkinter Game Client")
        self.root.geometry("1080x830")
        self.root.minsize(960, 740)

        # Branchement des logs réseau
        self.client.log_callback = self.log_network_event

        self._init_vars()
        self._build_ui()
        self._bind_events()
        self._redraw_current_canvas()

        # Démarrage de la boucle de consommation de la file asynchrone
        self.root.after(30, self._process_gui_queue)

        # Détection d'une session locale sauvegardée
        self._check_saved_session()

        # Initialisation du statut de connexion
        if self.client.is_connected():
            self._set_status(f"Connecté à {self.client.host}:{self.client.port}", "#00E676")
            self.connect_btn.configure(text="🔴 Déconnecter", fg_color=("#DC2626", "#B91C1C"))
        else:
            self._set_status("Déconnecté", "#FF5252")

        self.root.after(200, self._refresh)

    def _init_vars(self) -> None:
        """Initialise les variables d'état et d'affichage."""
        self._is_busy: bool = False
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

        self.room_badge_var = tk.StringVar(value="🏠 Salon : aucun")
        self.chat_scope_var = tk.StringVar(value="Salon")

        # Données locales pour les salons et le chat
        self.rooms_data: list[dict[str, Any]] = [
            {"room_id": "general", "name": "Salon Général", "players": ["Joueur"], "players_count": 1, "status": "LIBRE"},
            {"room_id": "defi_m1", "name": "Salon Défi Réseaux M1", "players": ["Alice", "Bob"], "players_count": 2, "status": "EN_COURS"},
            {"room_id": "speedrun", "name": "Salon Speedrun ⚡", "players": [], "players_count": 0, "status": "LIBRE"},
        ]
        self.chat_history: list[dict[str, Any]] = []

    def _build_ui(self) -> None:
        """Construit l'interface graphique moderne CustomTkinter."""
        self.main_container = ctk.CTkFrame(self.root, corner_radius=0, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=16, pady=12)

        # 1. BANDEAU SUPÉRIEUR : Branding, Statut, Dark/Light Switch & Connexion
        self._build_top_header(self.main_container)

        # 2. NAVIGATION PAR ONGLETS (Jeu, Chat, Salons, Inspecteur)
        self.tabview = ctk.CTkTabview(self.main_container, corner_radius=14)
        self.tabview.pack(fill="both", expand=True, pady=(6, 0))

        self.tab_game = self.tabview.add("🎮 Plateau de Jeu")
        self.tab_chat = self.tabview.add("💬 Chat en Direct")
        self.tab_rooms = self.tabview.add("🏠 Salons de Jeu")
        self.tab_inspector = self.tabview.add("🔍 Inspecteur Réseau")

        # Construction des contenus de chaque onglet
        self._build_game_tab(self.tab_game)
        self._build_chat_tab(self.tab_chat)
        self._build_rooms_tab(self.tab_rooms)
        self._build_inspector_tab(self.tab_inspector)

    def _build_top_header(self, parent: ctk.CTkFrame) -> None:
        """Construit la barre supérieure avec switch d'apparence et formulaire de connexion."""
        header_card = ctk.CTkFrame(parent, corner_radius=12, fg_color=THEME["bg_card"], border_width=1, border_color=THEME["border"])
        header_card.pack(fill="x", pady=(0, 6), padx=2)

        # Ligne 1 : Titre, Badges de statut et Switch Dark/Light Mode
        row1 = ctk.CTkFrame(header_card, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=(10, 6))

        title_box = ctk.CTkFrame(row1, fg_color="transparent")
        title_box.pack(side="left")

        ctk.CTkLabel(
            title_box,
            text="🎮 PENDU RÉSEAU",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=THEME["accent_primary"],
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            title_box,
            text="Client Moderne CustomTkinter",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_secondary"],
        ).pack(side="left", pady=(3, 0))

        # Droite : Switch de thème et Badges d'état
        right_box = ctk.CTkFrame(row1, fg_color="transparent")
        right_box.pack(side="right")

        # Switch Thème Clair / Sombre
        self.mode_switch = ctk.CTkSwitch(
            right_box,
            text="Mode Sombre",
            font=ctk.CTkFont(size=12),
            command=self._toggle_appearance_mode,
        )
        self.mode_switch.select()
        self.mode_switch.pack(side="left", padx=(0, 16))

        # Indicateur LED
        self.status_canvas = tk.Canvas(right_box, width=14, height=14, highlightthickness=0, bg="#181C24")
        self.status_circle = self.status_canvas.create_oval(2, 2, 12, 12, fill="#FF5252", outline="")
        self.status_canvas.pack(side="left", padx=(0, 6))

        self.status_label = ctk.CTkLabel(
            right_box,
            text="Déconnecté",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=THEME["text_primary"],
        )
        self.status_label.pack(side="left", padx=(0, 10))

        self.session_info_label = ctk.CTkLabel(
            right_box,
            text="",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color=THEME["accent_primary"],
        )
        self.session_info_label.pack(side="left")

        # Ligne 2 : Formulaire de connexion dynamique
        form_row = ctk.CTkFrame(header_card, fg_color="transparent")
        form_row.pack(fill="x", padx=14, pady=(0, 10))
        
        self.tls_check = ctk.CTkCheckBox(form_row, text="TLS", variable=self.tls_var, width=60, font=ctk.CTkFont(size=12))
        self.tls_check.pack(side="left", padx=(0, 8))

        ctk.CTkLabel(form_row, text="Hôte :", font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"]).pack(side="left", padx=(0, 4))
        self.host_entry = ctk.CTkEntry(form_row, textvariable=self.host_var, width=120, height=28, font=ctk.CTkFont(size=12))
        self.host_entry.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(form_row, text="Port :", font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"]).pack(side="left", padx=(0, 4))
        self.port_entry = ctk.CTkEntry(form_row, textvariable=self.port_var, width=70, height=28, font=ctk.CTkFont(size=12))
        self.port_entry.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(form_row, text="Pseudo :", font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"]).pack(side="left", padx=(0, 4))
        self.pseudo_entry = ctk.CTkEntry(form_row, textvariable=self.pseudo_var, width=100, height=28, font=ctk.CTkFont(size=12))
        self.pseudo_entry.pack(side="left", padx=(0, 12))

        self.connect_btn = ctk.CTkButton(
            form_row,
            text="🔌 Connexion",
            height=28,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=THEME["accent_primary"],
            hover_color="#0284C7",
            command=self.connect_or_disconnect,
        )
        self.connect_btn.pack(side="left", padx=(0, 8))

        self.resume_btn = ctk.CTkButton(
            form_row,
            text="🔄 Reprendre session",
            height=28,
            font=ctk.CTkFont(size=12),
            fg_color=THEME["bg_elevated"],
            hover_color=THEME["bg_hover"],
            text_color=THEME["text_primary"],
            command=self.resume_existing_session,
        )
        self.resume_btn.pack(side="left", padx=(0, 8))

        self.discover_btn = ctk.CTkButton(
            form_row,
            text="🔍 Découvrir",
            height=28,
            width=90,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=THEME["bg_elevated"],
            hover_color=THEME["bg_hover"],
            text_color=THEME["accent_primary"],
            command=self.discover_local_servers,
        )
        self.discover_btn.pack(side="left", padx=(0, 12))

        # Badge salon actif
        self.room_badge = ctk.CTkLabel(
            form_row,
            textvariable=self.room_badge_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=THEME["accent_warning"],
        )
        self.room_badge.pack(side="right")

    # --- ONGLET 1 : JEU DU PENDU ---

    def _build_game_tab(self, parent: ctk.CTkFrame) -> None:
        """Construit le plateau de jeu du pendu avec potence Canvas, mot masqué et clavier virtuel."""
        top_split = ctk.CTkFrame(parent, fg_color="transparent")
        top_split.pack(fill="x", padx=12, pady=(8, 4))

        # Carte gauche : Canvas vectoriel de la potence
        canvas_card = ctk.CTkFrame(top_split, corner_radius=12, fg_color=THEME["bg_card"], border_width=1, border_color=THEME["border"])
        canvas_card.pack(side="left", padx=(0, 10), pady=4)

        self.canvas = tk.Canvas(
            canvas_card,
            width=260,
            height=200,
            highlightthickness=0,
            bg="#14171F",
        )
        self.canvas.pack(padx=8, pady=8)

        # Carte droite : Mot masqué + Badges statistiques + Feedback
        info_card = ctk.CTkFrame(top_split, corner_radius=12, fg_color=THEME["bg_card"], border_width=1, border_color=THEME["border"])
        info_card.pack(side="right", fill="both", expand=True, pady=4)

        # Mot masqué grand format
        self.word_label = ctk.CTkLabel(
            info_card,
            textvariable=self.word_var,
            font=ctk.CTkFont(family="Consolas", size=34, weight="bold"),
            text_color=THEME["text_primary"],
        )
        self.word_label.pack(pady=(16, 10))

        # Ligne de badges de statistiques
        badges_frame = ctk.CTkFrame(info_card, fg_color="transparent")
        badges_frame.pack(pady=(0, 8))

        self.timer_badge = ctk.CTkLabel(
            badges_frame,
            textvariable=self.timer_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=THEME["bg_elevated"],
            text_color=THEME["accent_primary"],
            corner_radius=8,
            padx=12,
            pady=4,
        )
        self.timer_badge.pack(side="left", padx=4)

        self.lives_badge = ctk.CTkLabel(
            badges_frame,
            textvariable=self.lives_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=THEME["bg_elevated"],
            text_color=THEME["accent_success"],
            corner_radius=8,
            padx=12,
            pady=4,
        )
        self.lives_badge.pack(side="left", padx=4)

        self.errors_badge = ctk.CTkLabel(
            badges_frame,
            textvariable=self.errors_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=THEME["bg_elevated"],
            text_color=THEME["accent_danger"],
            corner_radius=8,
            padx=12,
            pady=4,
        )
        self.errors_badge.pack(side="left", padx=4)

        # Feedback textuel
        self.feedback_label = ctk.CTkLabel(
            info_card,
            textvariable=self.feedback_var,
            font=ctk.CTkFont(size=12),
            text_color=THEME["text_secondary"],
        )
        self.feedback_label.pack(pady=(0, 10))

        # Carte Clavier Virtuel Interactif A-Z
        keyboard_card = ctk.CTkFrame(parent, corner_radius=12, fg_color=THEME["bg_card"], border_width=1, border_color=THEME["border"])
        keyboard_card.pack(fill="x", padx=12, pady=(4, 6))

        ctk.CTkLabel(
            keyboard_card,
            text="CLAVIER VIRTUEL (CLIQUEZ OU TAPEZ SUR VOTRE CLAVIER PHYSIQUE)",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=THEME["text_secondary"],
        ).pack(pady=(6, 4))

        self.buttons: dict[str, LetterButton] = {}
        rows = [
            list(ascii_uppercase[:9]),     # A - I
            list(ascii_uppercase[9:18]),   # J - R
            list(ascii_uppercase[18:]),    # S - Z
        ]

        for row_letters in rows:
            r_frame = ctk.CTkFrame(keyboard_card, fg_color="transparent")
            r_frame.pack(pady=2)
            for letter in row_letters:
                btn = LetterButton(
                    r_frame,
                    text=letter,
                    width=42,
                    height=36,
                    corner_radius=8,
                    font=ctk.CTkFont(size=13, weight="bold"),
                    fg_color=THEME["bg_elevated"],
                    hover_color=THEME["bg_hover"],
                    text_color=THEME["text_primary"],
                    command=lambda l=letter: self.play(l),
                )
                btn.pack(side="left", padx=3)
                self.buttons[letter] = btn

        # Actions de jeu
        actions_bar = ctk.CTkFrame(parent, fg_color="transparent")
        actions_bar.pack(pady=6)

        self.new_game_btn = ctk.CTkButton(
            actions_bar,
            text="✨ Nouvelle Manche",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=THEME["accent_success"],
            hover_color="#15803D",
            text_color="#052410",
            height=34,
            command=self.start_new_game,
        )
        self.new_game_btn.pack(side="left", padx=6)

        self.quit_btn = ctk.CTkButton(
            actions_bar,
            text="🚪 Abandonner",
            font=ctk.CTkFont(size=12),
            fg_color=THEME["accent_danger"],
            hover_color="#991B1B",
            text_color="white",
            height=34,
            command=self.quit_game,
        )
        self.quit_btn.pack(side="left", padx=6)

        self.disconnect_sim_btn = ctk.CTkButton(
            actions_bar,
            text="⚡ Coupure simulée (Idempotence)",
            font=ctk.CTkFont(size=12),
            fg_color=THEME["bg_elevated"],
            hover_color=THEME["bg_hover"],
            text_color=THEME["accent_warning"],
            height=34,
            command=self.simulate_disconnect,
        )
        self.disconnect_sim_btn.pack(side="left", padx=6)

    # --- ONGLET 2 : CHAT EN DIRECT (EXTENSION C) ---

    def _build_chat_tab(self, parent: ctk.CTkFrame) -> None:
        """Construit le salon de discussion multi-joueurs (Extension C)."""
        chat_top = ctk.CTkFrame(parent, fg_color="transparent")
        chat_top.pack(fill="x", padx=14, pady=(8, 4))

        ctk.CTkLabel(
            chat_top,
            text="💬 Discussion en direct avec les joueurs",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["text_primary"],
        ).pack(side="left")

        # Sélecteur de portée de chat (Salon ou Global)
        self.chat_scope_seg = ctk.CTkSegmentedButton(
            chat_top,
            values=["Salon Courant", "Chat Global"],
            command=self._on_chat_scope_change,
        )
        self.chat_scope_seg.set("Salon Courant")
        self.chat_scope_seg.pack(side="right")

        # Zone des messages scrollable
        self.chat_messages_frame = ctk.CTkScrollableFrame(
            parent,
            corner_radius=12,
            fg_color=THEME["bg_card"],
            border_width=1,
            border_color=THEME["border"],
            height=380,
        )
        self.chat_messages_frame.pack(fill="both", expand=True, padx=14, pady=4)

        # Affichage des messages initiaux
        self._refresh_chat_display()

        # Barre de saisie de message
        input_bar = ctk.CTkFrame(parent, fg_color="transparent")
        input_bar.pack(fill="x", padx=14, pady=(6, 10))

        self.chat_entry = ctk.CTkEntry(
            input_bar,
            placeholder_text="Écrivez votre message... (Appuyez sur Entrée pour envoyer)",
            height=36,
            font=ctk.CTkFont(size=12),
        )
        self.chat_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.chat_entry.bind("<Return>", lambda _: self._send_chat_message())

        self.chat_send_btn = ctk.CTkButton(
            input_bar,
            text="Envoyer 🚀",
            width=100,
            height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=THEME["accent_primary"],
            hover_color="#0284C7",
            command=self._send_chat_message,
        )
        self.chat_send_btn.pack(side="right")

    def _on_chat_scope_change(self, value: str) -> None:
        self.chat_scope_var.set(value)
        self._refresh_chat_display()

    def _visible_messages(self) -> list[dict[str, Any]]:
        """Renvoie les messages à afficher selon l'onglet choisi."""
        if self.chat_scope_seg.get() == "Chat Global":
            return [m for m in self.chat_history if m["scope"] == "global"]
        return [
            m for m in self.chat_history
            if m["scope"] == "room" and m["room_id"] == self.current_room_id
        ]

    def _refresh_chat_display(self) -> None:
        """Réaffiche l'ensemble des bulles de messages du chat."""
        for widget in self.chat_messages_frame.winfo_children():
            widget.destroy()

        for msg in self._visible_messages():
            bubble = ctk.CTkFrame(self.chat_messages_frame, corner_radius=10, fg_color=THEME["bg_elevated"])
            bubble.pack(fill="x", padx=6, pady=3)

            sender_color = THEME["accent_primary"]
            if msg["sender"] == "Système":
                sender_color = THEME["accent_warning"]
            elif msg["sender"] == self.pseudo_var.get():
                sender_color = THEME["accent_success"]

            head = ctk.CTkFrame(bubble, fg_color="transparent")
            head.pack(fill="x", padx=8, pady=(4, 0))

            ctk.CTkLabel(
                head,
                text=msg["sender"],
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=sender_color,
            ).pack(side="left")

            ctk.CTkLabel(
                head,
                text=f"[{msg.get('time', '')}] • {("Salon" if msg["scope"] == "room" else "Global")}",
                font=ctk.CTkFont(size=9),
                text_color=THEME["text_muted"],
            ).pack(side="right")

            ctk.CTkLabel(
                bubble,
                text=msg["text"],
                font=ctk.CTkFont(size=12),
                text_color=THEME["text_primary"],
                wraplength=760,
                justify="left",
            ).pack(anchor="w", padx=8, pady=(2, 6))

    def _add_chat_line(self, payload: dict) -> None:
        """Ajoute un message (push reçu ou réponse à mon envoi) à l'historique."""
        self.chat_history.append({
            "sender": payload.get("player", "?"),
            "text": payload.get("text", ""),
            "time": datetime.now().strftime("%H:%M:%S"),
            "scope": payload.get("scope", "global"),     # "global" ou "room"
            "room_id": payload.get("room_id"),
        })
        self._refresh_chat_display()
    
    def _send_chat_message(self) -> None:
        text = self.chat_entry.get().strip()
        if not text:
            return
        scope = "room" if self.chat_scope_seg.get() == "Salon Courant" else "global"
        try:
            resp = self.client.chat(text, scope)
        except (ConnectionError, OSError) as e:
            messagebox.showerror("Erreur réseau", str(e))
            return
        if resp.type == "ERROR":
            messagebox.showwarning("Chat", resp.payload.get("message", "Message refusé."))
            return
        self.chat_entry.delete(0, "end")
        self._add_chat_line(resp.payload)   # l'expéditeur ne reçoit pas son propre push

    # --- ONGLET 3 : SALONS DE JEU (EXTENSION B) ---

    def _build_rooms_tab(self, parent: ctk.CTkFrame) -> None:
        """Construit le gestionnaire de salles de jeu / salons multi-joueurs (Extension B)."""
        top_bar = ctk.CTkFrame(parent, fg_color="transparent")
        top_bar.pack(fill="x", padx=14, pady=(8, 4))

        ctk.CTkLabel(
            top_bar,
            text="🏠 Gestion des Salles de Jeu (LIST, CREATE, JOIN, LEAVE)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["text_primary"],
        ).pack(side="left")

        refresh_btn = ctk.CTkButton(
            top_bar,
            text="🔄 Actualiser les salons",
            width=130,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color=THEME["bg_elevated"],
            hover_color=THEME["bg_hover"],
            text_color=THEME["text_primary"],
            command=self._refresh_rooms_list,
        )
        refresh_btn.pack(side="right")

        # Formulaire de création de salon
        create_frame = ctk.CTkFrame(parent, corner_radius=12, fg_color=THEME["bg_card"], border_width=1, border_color=THEME["border"])
        create_frame.pack(fill="x", padx=14, pady=6)

        ctk.CTkLabel(
            create_frame,
            text="Créer un nouveau salon :",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=THEME["text_primary"],
        ).pack(side="left", padx=(12, 8), pady=8)

        self.new_room_entry = ctk.CTkEntry(
            create_frame,
            placeholder_text="Nom du salon (ex: Salon VIP Réseaux)...",
            height=30,
            width=280,
            font=ctk.CTkFont(size=12),
        )
        self.new_room_entry.pack(side="left", padx=(0, 10))

        create_btn = ctk.CTkButton(
            create_frame,
            text="➕ Créer et Rejoindre",
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=THEME["accent_primary"],
            hover_color="#0284C7",
            command=self._create_room_action,
        )
        create_btn.pack(side="left")

        # Liste scrollable des salons
        self.rooms_scroll_frame = ctk.CTkScrollableFrame(
            parent,
            corner_radius=12,
            fg_color=THEME["bg_card"],
            border_width=1,
            border_color=THEME["border"],
            height=360,
        )
        self.rooms_scroll_frame.pack(fill="both", expand=True, padx=14, pady=(4, 10))

        self._render_rooms_list()

    def _render_rooms_list(self) -> None:
        """Affiche les cartes de salons disponibles avec actions Rejoindre/Quitter."""
        for widget in self.rooms_scroll_frame.winfo_children():
            widget.destroy()

        for room in self.rooms_data:
            r_id = room["room_id"]
            card = ctk.CTkFrame(self.rooms_scroll_frame, corner_radius=10, fg_color=THEME["bg_elevated"])
            card.pack(fill="x", padx=6, pady=4)

            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", padx=10, pady=8)

            ctk.CTkLabel(
                left,
                text=room["name"],
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=THEME["text_primary"],
            ).pack(anchor="w")

            status_str = f"Statut : {room.get('status', 'LIBRE')} • Joueurs : {len(room.get('players', []))}"
            ctk.CTkLabel(
                left,
                text=status_str,
                font=ctk.CTkFont(size=11),
                text_color=THEME["text_secondary"],
            ).pack(anchor="w")

            right = ctk.CTkFrame(card, fg_color="transparent")
            right.pack(side="right", padx=10, pady=8)

            if r_id == self.current_room_id:
                ctk.CTkLabel(
                    right,
                    text="✔ Vous êtes ici",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=THEME["accent_success"],
                ).pack(side="left", padx=(0, 6))

                if r_id != "general":
                    leave_btn = ctk.CTkButton(
                        right,
                        text="🚪 Quitter",
                        width=80,
                        height=28,
                        fg_color=THEME["accent_danger"],
                        hover_color="#991B1B",
                        command=self._leave_room_action,
                    )
                    leave_btn.pack(side="left")
            else:
                join_btn = ctk.CTkButton(
                    right,
                    text="➡️ Rejoindre",
                    width=90,
                    height=28,
                    fg_color=THEME["accent_primary"],
                    hover_color="#0284C7",
                    command=lambda r=room: self._join_room_action(r),
                )
                join_btn.pack(side="left")

    def _refresh_rooms_list(self) -> None:
        """Demande la liste des salons au serveur via LIST_ROOMS."""
        if self.client.is_connected() and self.client.session_id:
            def task():
                return self.client.request("LIST_ROOMS")

            def on_success(resp: Message):
                if resp.type == "ROOMS_LIST":
                    rooms = resp.payload.get("rooms", [])
                    if rooms:
                        self.rooms_data = rooms
                    self._render_rooms_list()

            self._run_async(task, on_success=on_success)
        else:
            self._render_rooms_list()

    def _create_room_action(self) -> None:
        """Crée un salon via CREATE_ROOM."""
        name = self.new_room_entry.get().strip()
        if not name:
            messagebox.showwarning("Nom requis", "Veuillez entrer un nom pour le salon.")
            return

        new_id = f"room_{len(self.rooms_data) + 1}"
        new_room = {
            "room_id": new_id,
            "name": name,
            "players": [self.pseudo_var.get()],
            "players_count": 1,
            "status": "LIBRE",
        }
        self.rooms_data.append(new_room)
        self.current_room_id = new_id
        self.current_room_name = name
        self.room_badge_var.set(f"🏠 Salon : {name}")
        self.new_room_entry.delete(0, "end")
        self._render_rooms_list()

        if self.client.is_connected() and self.client.session_id:
            self._run_async(lambda: self.client.request("CREATE_ROOM", {"name": name}))

    def _join_room_action(self, room: dict[str, Any]) -> None:
        """Rejoint un salon. L'affichage ne change qu'après la confirmation ROOM du serveur."""
        if not self.client.is_connected() or not self.client.session_id:
            messagebox.showwarning("Connexion requise", "Connectez-vous d'abord.")
            return
        try:
            resp = self.client.join_room(room["room_id"])
        except (ConnectionError, OSError) as e:
            messagebox.showerror("Erreur réseau", str(e))
            return
        if resp.type == "ERROR":
            messagebox.showwarning("Salon", resp.payload.get("message", "Impossible de rejoindre le salon."))
            return
        self.current_room_id = resp.payload.get("room_id")
        self.current_room_name = room["name"]
        self.room_badge_var.set(f"🏠 Salon : {self.current_room_name}")
        self._render_rooms_list()


    def _leave_room_action(self) -> None:
        """Quitte le salon courant, uniquement si le serveur confirme."""
        if not self.client.is_connected() or not self.client.session_id:
            return
        try:
            resp = self.client.leave_room()
        except (ConnectionError, OSError) as e:
            messagebox.showerror("Erreur réseau", str(e))
            return
        if resp.type == "ERROR":
            messagebox.showwarning("Salon", resp.payload.get("message", "Impossible de quitter le salon."))
            return
        self.current_room_id = None
        self.current_room_name = None
        self.room_badge_var.set("🏠 Salon : aucun")
        self._render_rooms_list()

    # --- ONGLET 4 : INSPECTEUR RÉSEAU ---

    def _build_inspector_tab(self, parent: ctk.CTkFrame) -> None:
        """Construit le visualiseur de trames TCP délimitées par \\n."""
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(8, 4))

        ctk.CTkLabel(
            top,
            text="🔍 Trames JSON TCP délimitées par \\n",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["text_primary"],
        ).pack(side="left")

        clear_btn = ctk.CTkButton(
            top,
            text="🗑 Effacer les logs",
            width=120,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color=THEME["bg_elevated"],
            hover_color=THEME["bg_hover"],
            text_color=THEME["text_primary"],
            command=self._clear_logs,
        )
        clear_btn.pack(side="right")

        self.log_text = ctk.CTkTextbox(
            parent,
            corner_radius=12,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word",
        )
        self.log_text.pack(fill="both", expand=True, padx=14, pady=(4, 10))

        # Configuration des tags de coloration syntaxique
        self.log_text.tag_config("ENVOI", foreground="#38BDF8")
        self.log_text.tag_config("REÇU", foreground="#00E676")
        self.log_text.tag_config("CONNEXION", foreground="#A78BFA")
        self.log_text.tag_config("RECONNEXION", foreground="#F59E0B")
        self.log_text.tag_config("ERREUR", foreground="#FF5252")
        self.log_text.tag_config("INFO", foreground="#94A3B8")

    def _toggle_inspector(self) -> None:
        """Bascule la vue vers l'inspecteur réseau (compatibilité test)."""
        self.inspector_visible = not self.inspector_visible
        if self.inspector_visible:
            self.tabview.set("🔍 Inspecteur Réseau")
        else:
            self.tabview.set("🎮 Plateau de Jeu")

    def _clear_logs(self) -> None:
        """Efface les logs de la console."""
        self.log_text.delete("1.0", "end")

    # --- DESSIN VECTORIEL DU PENDU & THÉMATISATION CANVAS ---

    def _toggle_appearance_mode(self) -> None:
        """Alterne entre Mode Sombre et Mode Clair."""
        current = ctk.get_appearance_mode().lower()
        if current == "dark":
            ctk.set_appearance_mode("light")
            self.mode_switch.configure(text="Mode Clair")
        else:
            ctk.set_appearance_mode("dark")
            self.mode_switch.configure(text="Mode Sombre")
        self._redraw_current_canvas()

    def _redraw_current_canvas(self) -> None:
        """Redessine le canvas avec les couleurs adaptées au mode courant."""
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        canvas_bg = "#14171F" if is_dark else "#FFFFFF"
        self.canvas.config(bg=canvas_bg)
        self.status_canvas.config(bg=canvas_bg)
        self._draw_hangman_stage(self._current_errors, self._current_status)

    def _draw_gallows(self) -> None:
        """Dessine la structure épurée de la potence."""
        self.canvas.delete("all")
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        wood = "#475569" if is_dark else "#64748B"
        base_decor = "#2D3748" if is_dark else "#CBD5E1"
        rope = "#F59E0B" if is_dark else "#D97706"

        # Base géométrique
        self.canvas.create_line(30, 185, 230, 185, width=4, fill=wood, capstyle="round")
        self.canvas.create_line(45, 185, 45, 191, width=3, fill=base_decor, capstyle="round")
        self.canvas.create_line(215, 185, 215, 191, width=3, fill=base_decor, capstyle="round")

        # Poteau vertical
        self.canvas.create_line(70, 185, 70, 25, width=4, fill=wood, capstyle="round")

        # Poutre horizontale
        self.canvas.create_line(70, 25, 180, 25, width=4, fill=wood, capstyle="round")

        # Étai diagonal
        self.canvas.create_line(70, 60, 105, 25, width=3, fill=wood, capstyle="round")

        # Corde
        self.canvas.create_line(180, 25, 180, 55, width=2, fill=rope, capstyle="round")

    def _draw_hangman_stage(self, errors_made: int, status: str | None = None) -> None:
        """Dessine les parties du bonhomme pendu selon le nombre d'erreurs."""
        self._current_errors = errors_made
        self._current_status = status
        self._draw_gallows()

        is_dark = ctk.get_appearance_mode().lower() == "dark"
        color = "#FF5252" if is_dark else "#DC2626"
        fill_head = "#4A191F" if is_dark else "#FEE2E2"

        if errors_made >= 1:
            # Tête
            self.canvas.create_oval(162, 55, 198, 91, width=3, outline=color, fill=fill_head)
        if errors_made >= 2:
            # Corps
            self.canvas.create_line(180, 91, 180, 140, width=3, fill=color, capstyle="round")
        if errors_made >= 3:
            # Bras gauche
            self.canvas.create_line(180, 104, 155, 124, width=3, fill=color, capstyle="round")
        if errors_made >= 4:
            # Bras droit
            self.canvas.create_line(180, 104, 205, 124, width=3, fill=color, capstyle="round")
        if errors_made >= 5:
            # Jambe gauche
            self.canvas.create_line(180, 140, 155, 175, width=3, fill=color, capstyle="round")
        if errors_made >= 6:
            # Jambe droite
            self.canvas.create_line(180, 140, 205, 175, width=3, fill=color, capstyle="round")
            # Yeux en croix (X X)
            self.canvas.create_line(170, 68, 175, 73, width=2, fill=color)
            self.canvas.create_line(175, 68, 170, 73, width=2, fill=color)
            self.canvas.create_line(185, 68, 190, 73, width=2, fill=color)
            self.canvas.create_line(190, 68, 185, 73, width=2, fill=color)

        if status == "GAGNE":
            crown = "#00E676" if is_dark else "#16A34A"
            self.canvas.create_polygon(
                166, 52, 173, 44, 180, 50, 187, 44, 194, 52,
                fill=crown,
                outline="",
            )

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

    # --- ASYNCHRONE & MULTITHREADING ---

    def _run_async(
        self,
        task: Callable[..., Any],
        args: tuple = (),
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Exécute une opération réseau en arrière-plan sans bloquer CustomTkinter."""
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
        """Réactive la possibilité d'émettre une action réseau."""
        self._is_busy = False

    def _process_gui_queue(self) -> None:
        """Traite les retours réseau et logs sur le thread UI principal."""
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
            if self.root:
                self.root.after(30, self._process_gui_queue)

    def _refresh(self) -> None:
            try:
                self.client.poll()
            except (ConnectionError, OSError):
                self.client.close()
                self._set_status("Déconnecté", "#FF5252")
            if self.client.inbox:
                for m in self.client.inbox:
                    self._add_chat_line(m)
                self.client.inbox.clear()
            self.root.after(200, self._refresh)

    def log_network_event(self, direction: str, text: str) -> None:
        """Point d'entrée thread-safe pour les logs de GameClient."""
        self._gui_queue.put(("LOG", (direction, text)))

    def _insert_log(self, direction: str, text: str) -> None:
        """Insère une ligne colorée dans l'inspecteur réseau."""
        tag = direction if direction in ("ENVOI", "REÇU", "CONNEXION", "RECONNEXION", "ERREUR", "INFO") else None
        prefix = f"[{direction}] "
        self.log_text.insert("end", prefix, tag)
        self.log_text.insert("end", f"{text}\n")
        self.log_text.see("end")

    # --- ACTIONS RÉSEAU ET ÉTATS DU JEU ---

    def _bind_events(self) -> None:
        """Associe les raccourcis clavier physiques et la fermeture de fenêtre."""
        self.root.bind("<Key>", self._on_key_press)
        self.host_entry.bind("<Return>", lambda _: self.connect_or_disconnect())
        self.port_entry.bind("<Return>", lambda _: self.connect_or_disconnect())
        self.pseudo_entry.bind("<Return>", lambda _: self.connect_or_disconnect())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_key_press(self, event: tk.Event) -> None:
        """Capture la saisie physique des lettres A-Z pour jouer instantanément."""
        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, tk.Text)) or "entry" in str(focused).lower():
            return

        char = (event.char or "").upper()
        if char in self.buttons and self.buttons[char].cget("state") == "normal":
            self.play(char)

    def _set_status(self, text: str, color: str) -> None:
        """Met à jour l'indicateur LED et le libellé de statut."""
        self.status_canvas.itemconfig(self.status_circle, fill=color)
        self.status_label.configure(text=text)

    def _set_feedback(self, text: str, color: tuple[str, str] | str | None = None) -> None:
        """Met à jour le message d'aide / ambiance."""
        self.feedback_var.set(text)
        if color:
            self.feedback_label.configure(text_color=color)
        else:
            self.feedback_label.configure(text_color=THEME["text_secondary"])

    def _check_saved_session(self) -> None:
        """Vérifie si un fichier session.json peut être repris."""
        if os.path.exists("session.json"):
            has_session = self.client.load_session("session.json")
            if has_session:
                self.resume_btn.configure(state="normal", text_color=THEME["accent_primary"])
                self.session_info_label.configure(
                    text=f"Session détectée ({self.client.player_name})"
                )
                return
        self.resume_btn.configure(state="disabled", text_color=THEME["text_muted"])

    def connect_or_disconnect(self) -> None:
        """Bascule entre Connexion et Déconnexion."""
        if self.client.is_connected():
            self.client.close()
            self._set_status("Déconnecté", "#FF5252")
            self.connect_btn.configure(text="🔌 Connexion", fg_color=THEME["accent_primary"])
            self._set_feedback("Connexion fermée.")
            return

        host = self.host_var.get().strip() or "127.0.0.1"
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("Port invalide", "Veuillez entrer un numéro de port valide (ex: 8888).")
            return

        pseudo = self.pseudo_var.get().strip() or "Joueur"
        use_tls = self.tls_var.get()

        self._set_status("Connexion en cours...", "#F59E0B")
        self.connect_btn.configure(state="disabled")

        def task():
            self.client.host = host
            self.client.port = port
            self.client.use_tls = use_tls
            self.client.connect()
            welcome = self.client.hello(pseudo)
            return welcome

        def on_success(welcome_resp: Message):
            self.connect_btn.configure(state="normal")
            if welcome_resp.type == "WELCOME":
                self._set_status(f"Connecté à {self.client.host}:{self.client.port}", "#00E676")
                self.connect_btn.configure(text="🔴 Déconnecter", fg_color=("#DC2626", "#B91C1C"))
                self.session_info_label.configure(
                    text=f"Session : {self.client.session_id[:8]}... | Joueur : {self.client.player_name}"
                )
                self.client.save_session("session.json")
                self._check_saved_session()
                self._set_feedback(f"Bienvenue {self.client.player_name} ! Lancement de la partie...", THEME["accent_success"])
                self.start_new_game()
            else:
                self._set_status("Erreur session", "#FF5252")
                messagebox.showerror("Erreur d'accueil", welcome_resp.payload.get("message", "Échec HELLO"))

        def on_error(exc: Exception):
            self.connect_btn.configure(state="normal", text="🔌 Connexion", fg_color=THEME["accent_primary"])
            self._set_status("Échec connexion", "#FF5252")
            self._set_feedback(f"Erreur de connexion : {exc}", THEME["accent_danger"])
            messagebox.showerror("Connexion impossible", f"Impossible d'ouvrir la socket vers {host}:{port} :\n{exc}")

        self._run_async(task, on_success=on_success, on_error=on_error)

    def start_session(self, player_name: str) -> None:
        """Méthode de compatibilité pour initialiser une session."""
        self.pseudo_var.set(player_name)
        self.connect_or_disconnect()

    def resume_existing_session(self) -> None:
        """Tente de reprendre la session stockée via RESUME."""
        if not self.client.session_id:
            if not self.client.load_session("session.json"):
                messagebox.showinfo("Aucune session", "Aucune session enregistrée à reprendre.")
                return

        # Synchronisation des paramètres réseau saisis dans l'IHM
        self.client.host = self.host_var.get().strip() or "127.0.0.1"
        try:
            self.client.port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("Port invalide", "Veuillez entrer un numéro de port valide (ex: 8888).")
            return
        self.client.use_tls = self.tls_var.get()

        self._set_status("Reprise de session...", "#F59E0B")

        def task():
            if not self.client.is_connected():
                self.client.connect()
            return self.client.resume()

        def on_success(resp: Message):
            if resp.type == "STATE":
                self._set_status(f"Connecté à {self.client.host}:{self.client.port}", "#00E676")
                self.connect_btn.configure(text="🔴 Déconnecter", fg_color=("#DC2626", "#B91C1C"))
                self.session_info_label.configure(
                    text=f"Session : {self.client.session_id[:8]}... | Joueur : {self.client.player_name}"
                )
                self._set_feedback("Session restaurée avec succès !", THEME["accent_success"])
                if resp.payload.get("status") == "IDLE":
                    self.start_new_game()
                else:
                    self.update_from_state(resp)
            else:
                messagebox.showwarning("Reprise impossible", resp.payload.get("message", "Session expirée"))
                self._set_status("Session expirée", "#FF5252")

        def on_error(exc: Exception):
            self._set_status("Déconnecté", "#FF5252")
            messagebox.showwarning("Reprise impossible", f"Erreur de reprise : {exc}")

        self._run_async(task, on_success=on_success, on_error=on_error)

    def discover_local_servers(self) -> None:
        """Sonde le réseau local en UDP Multicast pour trouver les serveurs actifs."""
        self._set_status("Recherche de serveurs...", "#F59E0B")
        self._set_feedback("Sondage UDP Multicast (IPv4 & IPv6) du réseau local en cours...")
        self.discover_btn.configure(state="disabled", text="🔍 Recherche...")

        def on_success(servers: list[dict[str, Any]]) -> None:
            self.discover_btn.configure(state="normal", text="🔍 Découvrir")
            if not servers:
                self._set_status("Aucun serveur trouvé", "#94A3B8")
                self._set_feedback("Aucun serveur de Pendu détecté sur le réseau local.")
                messagebox.showinfo(
                    "Découverte réseau",
                    "Aucun serveur de Pendu n'a répondu à la sonde UDP Multicast sur le réseau local.\n\n"
                    "Vérifiez que le serveur est bien démarré sur la machine distante ou locale."
                )
                return

            if len(servers) == 1:
                s = servers[0]
                self.host_var.set(s["ip"])
                self.port_var.set(str(s["port"]))
                if s.get("use_tls"):
                    self.tls_var.set(True)
                self._set_status(f"Serveur détecté ({s['ip']})", "#00E676")
                self._set_feedback(f"Serveur trouvé : {s['server_name']} sur {s['ip']}:{s['port']} !", THEME["accent_success"])
                messagebox.showinfo(
                    "Serveur détecté",
                    f"Serveur trouvé avec succès !\n\n"
                    f"• Nom : {s['server_name']}\n"
                    f"• Adresse : {s['ip']}:{s['port']}\n"
                    f"• Joueurs connectés : {s['players_count']}\n"
                    f"• Sécurité TLS : {'Oui 🔒' if s.get('use_tls') else 'Non'}\n\n"
                    "Les champs Hôte et Port ont été pré-remplis automatiquement."
                )
            else:
                self._show_server_picker_dialog(servers)

        def on_error(exc: Exception) -> None:
            self.discover_btn.configure(state="normal", text="🔍 Découvrir")
            self._set_status("Erreur découverte", "#FF5252")
            self._set_feedback(f"Échec sonde Multicast : {exc}", THEME["accent_danger"])

        self._run_async(lambda: discover_servers(timeout=1.2), on_success=on_success, on_error=on_error)

    def _show_server_picker_dialog(self, servers: list[dict[str, Any]]) -> None:
        """Affiche une boîte de dialogue pour choisir parmi plusieurs serveurs détectés."""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Serveurs détectés sur le réseau")
        dialog.geometry("520x340")
        dialog.transient(self.root)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text=f"🌐 {len(servers)} serveurs de Pendu détectés :",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["accent_primary"],
        ).pack(padx=16, pady=(16, 8), anchor="w")

        scroll = ctk.CTkScrollableFrame(dialog, height=200)
        scroll.pack(fill="both", expand=True, padx=16, pady=8)

        for s in servers:
            card = ctk.CTkFrame(scroll, fg_color=THEME["bg_elevated"], corner_radius=8)
            card.pack(fill="x", pady=4, padx=4)

            info_box = ctk.CTkFrame(card, fg_color="transparent")
            info_box.pack(side="left", padx=10, pady=8)

            ctk.CTkLabel(
                info_box,
                text=s["server_name"],
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=THEME["text_primary"],
            ).pack(anchor="w")

            tls_info = " • TLS 🔒" if s.get("use_tls") else ""
            ctk.CTkLabel(
                info_box,
                text=f"{s['ip']}:{s['port']} • {s['players_count']} joueur(s){tls_info}",
                font=ctk.CTkFont(size=11),
                text_color=THEME["text_secondary"],
            ).pack(anchor="w")

            def choose_srv(srv=s):
                self.host_var.set(srv["ip"])
                self.port_var.set(str(srv["port"]))
                if srv.get("use_tls"):
                    self.tls_var.set(True)
                self._set_status(f"Serveur sélectionné ({srv['ip']})", "#00E676")
                self._set_feedback(f"Serveur sélectionné : {srv['server_name']}", THEME["accent_success"])
                dialog.destroy()

            ctk.CTkButton(
                card,
                text="Sélectionner",
                width=90,
                height=28,
                fg_color=THEME["accent_primary"],
                hover_color="#0284C7",
                command=choose_srv,
            ).pack(side="right", padx=10, pady=8)

    def start_new_game(self) -> None:
        """Lance une nouvelle manche NEW_GAME."""
        if not self.client.is_connected() or not self.client.session_id:
            self.connect_or_disconnect()
            return

        # Réinitialisation de l'affichage du clavier virtuel
        for btn in self.buttons.values():
            btn.configure(
                state="normal",
                fg_color=THEME["bg_elevated"],
                text_color=THEME["text_primary"],
            )

        self._set_feedback("Démarrage d'une nouvelle manche...")

        def on_success(resp: Message):
            self.update_from_state(resp)
            self._set_feedback("Nouvelle manche commencée ! Choisissez une lettre.", THEME["accent_primary"])

        def on_error(exc: Exception):
            self._set_status("Déconnecté", "#FF5252")
            messagebox.showerror("Erreur", f"Erreur réseau lors de NEW_GAME : {exc}")

        self._run_async(self.client.new_game, on_success=on_success, on_error=on_error)

    def play(self, letter: str) -> None:
        """Propose une lettre au serveur."""
        letter_upper = letter.upper()
        if letter_upper in self.buttons:
            self.buttons[letter_upper].configure(
                state="disabled",
                fg_color=THEME["bg_card"],
                text_color=THEME["text_muted"],
            )

        def on_success(resp: Message):
            self.update_from_state(resp)

        def on_error(exc: Exception):
            self._set_status("Déconnecté", "#FF5252")
            messagebox.showerror("Erreur Réseau", f"Échec de l'envoi de la lettre : {exc}")

        self._run_async(self.client.guess, args=(letter_upper,), on_success=on_success, on_error=on_error)

    def quit_game(self) -> None:
        """Envoie QUIT au serveur."""
        if messagebox.askyesno("Abandonner", "Voulez-vous vraiment abandonner la partie ?"):
            def task():
                return self.client.quit_game()

            def on_success(_):
                self._stop_timer()
                self._set_status("Session clôturée", "#94A3B8")
                self.info_var.set("Session clôturée.")
                self.feedback_var.set("Partie abandonnée.")
                for btn in self.buttons.values():
                    btn.configure(state="disabled")

            def on_error(exc: Exception):
                messagebox.showwarning("Attention", f"Erreur lors de QUIT : {exc}")

            self._run_async(task, on_success=on_success, on_error=on_error)

    def simulate_disconnect(self) -> None:
        """Ferme la socket locale pour démontrer la tolérance aux pannes (RESUME)."""
        self.client.close()
        self._set_status("Socket coupée (Simulation)", "#F59E0B")
        self._set_feedback("Coupure simulée : cliquez sur une lettre pour tester le rejeu idempotent !", THEME["accent_warning"])
        messagebox.showinfo(
            "Coupure simulée",
            "La socket TCP locale a été fermée.\n\n"
            "Cliquez sur une lettre ou une action :\n"
            "Le client détectera la coupure, se reconnectera automatiquement, "
            "enverra RESUME et rejouera votre requête avec idempotence !"
        )

    def update_from_state(self, resp: Any) -> None:
        """Met à jour l'affichage avec le payload STATE."""
        if resp.type == "ERROR":
            messagebox.showwarning("Erreur Applicative", f"{resp.payload.get('code')} : {resp.payload.get('message')}")
            return

        p = resp.payload
        max_errors = p.get("max_errors", 6)
        raw_masked = p.get("masked_word", "")
        spaced_word = "  ".join(raw_masked.split()) if " " in raw_masked else "  ".join(list(raw_masked))
        self.word_var.set(spaced_word)

        errors_left = p.get("errors_left", max_errors)
        errors_made = max(0, max_errors - errors_left)

        self.info_var.set(f"Essais restants : {errors_left} / {max_errors}  (Erreurs : {errors_made})")
        self.lives_var.set(f"❤️ {errors_left} / {max_errors}")
        self.errors_var.set(f"💀 {errors_made} / {max_errors}")

        status = p.get("status")

        # Mise à jour graphique de la potence
        self._draw_hangman_stage(errors_made, status=status)

        # Mise à jour des boutons du clavier virtuel
        used = p.get("used_letters", [])
        masked = p.get("masked_word", "")
        for letter in used:
            letter_upper = letter.upper()
            if letter_upper in self.buttons:
                if letter_upper in masked:
                    self.buttons[letter_upper].configure(
                        state="disabled",
                        fg_color=THEME["accent_success_bg"],
                        text_color=THEME["accent_success"],
                    )
                else:
                    self.buttons[letter_upper].configure(
                        state="disabled",
                        fg_color=THEME["accent_danger_bg"],
                        text_color=THEME["accent_danger"],
                    )

        # Gestion des états de jeu
        if status == "EN_COURS":
            if self._timer_started_at is None:
                self._start_timer()
            self._set_feedback(f"Partie en cours. Erreurs : {errors_made}/{max_errors}")

        elif status in ("GAGNE", "PERDU", "ABANDONNE"):
            elapsed = self._stop_timer()
            for btn in self.buttons.values():
                btn.configure(state="disabled")

            secret = p.get("secret_word")
            msg = END_MESSAGES.get(status, f"Partie finie : {status}")
            if elapsed is not None:
                msg += f"\n\n⏱ Temps écoulé : {elapsed}"
            if secret and status == "PERDU":
                msg += f"\n\n📖 Le mot était : {secret}"
                self._set_feedback(f"Défaite ! Le mot était {secret}.", THEME["accent_danger"])
            elif status == "GAGNE":
                self._set_feedback("Victoire ! Vous avez trouvé le mot !", THEME["accent_success"])

            messagebox.showinfo("Fin de partie", msg)

    def _on_close(self) -> None:
        """Ferme proprement la socket et détruit la fenêtre."""
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
