import tkinter as tk
from string import ascii_uppercase
from tkinter import messagebox, scrolledtext, simpledialog
from typing import Any

from client.connection import GameClient

END_MESSAGES = {
    "GAGNE": "🎉 Félicitations ! Vous avez trouvé le mot !",
    "PERDU": "💀 Dommage, vous avez épuisé tous vos essais...",
    "ABANDONNE": "Partie abandonnée.",
}


class HangmanApp:
    def __init__(self, root: tk.Tk, client: GameClient) -> None:
        self.root = root
        self.client = client
        root.title("Pendu Réseau M1 — Client Graphique")
        root.geometry("820x720")
        root.minsize(750, 650)

        # Branchement des logs réseau du client vers l'inspecteur graphique
        self.client.log_callback = self.log_network_event

        self._build_ui()
        self._draw_gallows()

    def _build_ui(self) -> None:
        # --- 1. BANDEAU SUPÉRIEUR : STATUT & SESSION ---
        header_frame = tk.Frame(self.root, bg="#2C3E50", pady=8, padx=12)
        header_frame.pack(fill="x", side="top")

        self.status_canvas = tk.Canvas(header_frame, width=16, height=16, bg="#2C3E50", highlightthickness=0)
        self.status_canvas.pack(side="left", padx=(0, 6))
        self.status_circle = self.status_canvas.create_oval(2, 2, 14, 14, fill="#2ECC71", outline="")

        self.status_label = tk.Label(
            header_frame,
            text=f"Connecté à {self.client.host}:{self.client.port}",
            font=("Segoe UI", 10, "bold"),
            bg="#2C3E50",
            fg="white",
        )
        self.status_label.pack(side="left")

        self.session_info_label = tk.Label(
            header_frame,
            text="",
            font=("Segoe UI", 9),
            bg="#2C3E50",
            fg="#BDC3C7",
        )
        self.session_info_label.pack(side="right")

        # --- 2. ZONE CENTRALE : DESSIN DU PENDU & JEU ---
        content_frame = tk.Frame(self.root, pady=10, padx=15)
        content_frame.pack(fill="both", expand=True)

        # Colonne de gauche : Canvas du Pendu
        left_frame = tk.Frame(content_frame, bd=2, relief="groove", bg="#FAFAFA")
        left_frame.pack(side="left", fill="both", padx=(0, 15), pady=5)

        tk.Label(left_frame, text="Potence", font=("Segoe UI", 11, "bold"), bg="#FAFAFA", fg="#34495E").pack(pady=5)
        self.canvas = tk.Canvas(left_frame, width=220, height=250, bg="#FFFFFF", highlightthickness=0)
        self.canvas.pack(padx=10, pady=5)

        # Colonne de droite : Mot, Vies, Clavier
        right_frame = tk.Frame(content_frame)
        right_frame.pack(side="right", fill="both", expand=True, pady=5)

        self.word_var = tk.StringVar(value="_ _ _ _ _")
        word_label = tk.Label(
            right_frame,
            textvariable=self.word_var,
            font=("Consolas", 28, "bold"),
            fg="#2C3E50",
            pady=10,
        )
        word_label.pack()

        self.info_var = tk.StringVar(value="Essais restants : 6 / 6")
        self.info_label = tk.Label(
            right_frame,
            textvariable=self.info_var,
            font=("Segoe UI", 12),
            fg="#7F8C8D",
        )
        self.info_label.pack(pady=(0, 10))

        # Clavier virtuel A-Z
        keyboard_frame = tk.LabelFrame(right_frame, text="Lettres", font=("Segoe UI", 10, "bold"), padx=8, pady=8)
        keyboard_frame.pack(fill="x", pady=5)

        self.buttons: dict[str, tk.Button] = {}
        for i, letter in enumerate(ascii_uppercase):
            btn = tk.Button(
                keyboard_frame,
                text=letter,
                font=("Segoe UI", 10, "bold"),
                width=3,
                height=1,
                bg="#ECF0F1",
                activebackground="#BDC3C7",
                command=lambda l=letter: self.play(l),
            )
            btn.grid(row=i // 9, column=i % 9, padx=3, pady=3)
            self.buttons[letter] = btn

        # Boutons d'actions rapides
        actions_frame = tk.Frame(right_frame, pady=8)
        actions_frame.pack(fill="x")

        self.new_game_btn = tk.Button(
            actions_frame,
            text="✨ Nouvelle Manche",
            font=("Segoe UI", 9, "bold"),
            bg="#27AE60",
            fg="white",
            padx=10,
            command=self.start_new_game,
        )
        self.new_game_btn.pack(side="left", padx=4)

        self.quit_btn = tk.Button(
            actions_frame,
            text="🚪 Abandonner",
            font=("Segoe UI", 9),
            bg="#E74C3C",
            fg="white",
            padx=10,
            command=self.quit_game,
        )
        self.quit_btn.pack(side="left", padx=4)

        self.disconnect_sim_btn = tk.Button(
            actions_frame,
            text="⚡ Simuler Coupure Réseau",
            font=("Segoe UI", 9),
            bg="#F39C12",
            fg="white",
            padx=8,
            command=self.simulate_disconnect,
        )
        self.disconnect_sim_btn.pack(side="right", padx=4)

        # --- 3. BANDEAU INFÉRIEUR : INSPECTEUR RÉSEAU / LOGS ---
        log_frame = tk.LabelFrame(
            self.root,
            text="Inspecteur Réseau (Trames JSON TCP délimitées par \\n)",
            font=("Segoe UI", 10, "bold"),
            padx=8,
            pady=4,
        )
        log_frame.pack(fill="both", expand=True, side="bottom", padx=10, pady=(0, 10))

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=8,
            font=("Consolas", 9),
            bg="#1E1E1E",
            fg="#D4D4D4",
            insertbackground="white",
        )
        self.log_text.pack(fill="both", expand=True)

        # Balises de style pour les logs
        self.log_text.tag_config("ENVOI", foreground="#4EC9B0")
        self.log_text.tag_config("REÇU", foreground="#569CD6")
        self.log_text.tag_config("CONNEXION", foreground="#6A9955")
        self.log_text.tag_config("RECONNEXION", foreground="#DCDCAA")
        self.log_text.tag_config("ERREUR", foreground="#F44747")
        self.log_text.tag_config("INFO", foreground="#CE9178")

    def _set_status(self, text: str, color: str) -> None:
        self.status_canvas.itemconfig(self.status_circle, fill=color)
        self.status_label.config(text=text)

    def log_network_event(self, direction: str, text: str) -> None:
        """Affiche les échanges réseau dans la console graphique intégrée."""
        tag = direction if direction in ("ENVOI", "REÇU", "CONNEXION", "RECONNEXION", "ERREUR", "INFO") else None
        prefix = f"[{direction}] "
        self.log_text.insert("end", prefix, tag)
        self.log_text.insert("end", f"{text}\n")
        self.log_text.see("end")

    def _draw_gallows(self) -> None:
        """Dessine la potence de base."""
        self.canvas.delete("all")
        # Base
        self.canvas.create_line(20, 230, 200, 230, width=4, fill="#34495E")
        # Poteau vertical
        self.canvas.create_line(60, 230, 60, 30, width=4, fill="#34495E")
        # Poutre horizontale
        self.canvas.create_line(60, 30, 160, 30, width=4, fill="#34495E")
        # Étai diagonal
        self.canvas.create_line(60, 70, 100, 30, width=3, fill="#34495E")
        # Corde
        self.canvas.create_line(160, 30, 160, 65, width=2, fill="#E67E22")

    def _draw_hangman_stage(self, errors_made: int) -> None:
        """Dessine les parties du corps selon le nombre d'erreurs (0 à 6)."""
        self._draw_gallows()
        if errors_made >= 1:
            # Tête
            self.canvas.create_oval(140, 65, 180, 105, width=3, outline="#C0392B", fill="#FDEDEC")
        if errors_made >= 2:
            # Corps
            self.canvas.create_line(160, 105, 160, 165, width=3, fill="#C0392B")
        if errors_made >= 3:
            # Bras gauche
            self.canvas.create_line(160, 120, 130, 145, width=3, fill="#C0392B")
        if errors_made >= 4:
            # Bras droit
            self.canvas.create_line(160, 120, 190, 145, width=3, fill="#C0392B")
        if errors_made >= 5:
            # Jambe gauche
            self.canvas.create_line(160, 165, 135, 210, width=3, fill="#C0392B")
        if errors_made >= 6:
            # Jambe droite (Pendu complet)
            self.canvas.create_line(160, 165, 185, 210, width=3, fill="#C0392B")

    def start_session(self, player_name: str) -> None:
        """Effectue le handshake HELLO puis lance une partie."""
        try:
            welcome = self.client.hello(player_name)
            if welcome.type == "WELCOME":
                self.session_info_label.config(
                    text=f"Joueur : {self.client.player_name} | Session : {self.client.session_id[:8]}..."
                )
                self.client.save_session("session.json")
                self.start_new_game()
            else:
                messagebox.showerror("Erreur d'accueil", welcome.payload.get("message", "Échec HELLO"))
        except (ConnectionError, OSError) as e:
            self._set_status("Déconnecté", "#E74C3C")
            messagebox.showerror("Erreur Réseau", f"Impossible de joindre le serveur : {e}")

    def resume_existing_session(self) -> None:
        """Tente de reprendre la session stockée."""
        try:
            resp = self.client.resume()
            if resp.type == "STATE":
                self._set_status(f"Connecté à {self.client.host}:{self.client.port}", "#2ECC71")
                self.session_info_label.config(
                    text=f"Joueur : {self.client.player_name} | Session : {self.client.session_id[:8]}..."
                )
                if resp.payload.get("status") == "IDLE":
                    self.start_new_game()
                else:
                    self.update_from_state(resp)
            else:
                messagebox.showwarning("Reprise impossible", resp.payload.get("message", "Session expirée"))
                self.start_session(self.client.player_name or "Joueur")
        except Exception as e:
            messagebox.showwarning("Reprise impossible", f"Erreur de reprise : {e}")
            self.start_session(self.client.player_name or "Joueur")

    def start_new_game(self) -> None:
        """Lance une nouvelle manche NEW_GAME."""
        # Réinitialisation du clavier
        for btn in self.buttons.values():
            btn.config(state="normal", bg="#ECF0F1", fg="#2C3E50")

        try:
            resp = self.client.new_game()
            self.update_from_state(resp)
        except (ConnectionError, OSError) as e:
            self._set_status("Déconnecté", "#E74C3C")
            messagebox.showerror("Erreur", f"Erreur réseau lors de NEW_GAME : {e}")

    def play(self, letter: str) -> None:
        """Propose une lettre."""
        try:
            resp = self.client.guess(letter)
            self.update_from_state(resp)
        except (ConnectionError, OSError) as e:
            self._set_status("Déconnecté", "#E74C3C")
            messagebox.showerror("Erreur Réseau", f"Échec de l'envoi de la lettre : {e}")

    def quit_game(self) -> None:
        """Envoie QUIT."""
        if messagebox.askyesno("Abandonner", "Voulez-vous vraiment abandonner la partie ?"):
            try:
                resp = self.client.quit_game()
                self._set_status("Session terminée", "#95A5A6")
                self.info_var.set("Session clôturée.")
                for btn in self.buttons.values():
                    btn.config(state="disabled")
            except Exception as e:
                messagebox.showwarning("Attention", f"Erreur lors de QUIT : {e}")

    def simulate_disconnect(self) -> None:
        """Ferme la socket locale pour démontrer la reprise automatique (RESUME)."""
        self.client.close()
        self._set_status("Socket fermée (Simulation de coupure)", "#E67E22")
        messagebox.showinfo(
            "Coupure simulée",
            "La socket TCP a été fermée localement.\n\nCliquez sur une lettre ou une action : le client va détecter la coupure, rouvrir la socket, exécuter RESUME et rejouer votre action automatiquement (idempotence) !"
        )

    def update_from_state(self, resp: Any) -> None:
        """Met à jour l'affichage avec le payload STATE."""
        if resp.type == "ERROR":
            messagebox.showwarning("Erreur Applicative", f"{resp.payload.get('code')} : {resp.payload.get('message')}")
            return

        p = resp.payload
        max_errors = p.get("max_errors", 6)
        self.word_var.set(p.get("masked_word", ""))
        errors_left = p.get("errors_left", max_errors)
        errors_made = max(0, max_errors - errors_left)
        self.info_var.set(f"Essais restants : {errors_left} / {max_errors}  (Erreurs : {errors_made})")

        # Mise à jour graphique du pendu
        self._draw_hangman_stage(errors_made)

        # Désactivation des lettres déjà jouées
        used = p.get("used_letters", [])
        masked = p.get("masked_word", "")
        for letter in used:
            letter_upper = letter.upper()
            if letter_upper in self.buttons:
                if letter_upper in masked:
                    self.buttons[letter_upper].config(state="disabled", bg="#D4EFDF", fg="#196F3D")
                else:
                    self.buttons[letter_upper].config(state="disabled", bg="#FADBD8", fg="#922B21")

        # Vérification fin de partie
        status = p.get("status")
        if status in ("GAGNE", "PERDU", "ABANDONNE"):
            for btn in self.buttons.values():
                btn.config(state="disabled")

            secret = p.get("secret_word")
            msg = END_MESSAGES.get(status, f"Partie finie : {status}")
            if secret and status == "PERDU":
                msg += f"\n\nLe mot était : {secret}"
            messagebox.showinfo("Fin de partie", msg)


def main() -> None:
    root = tk.Tk()
    root.withdraw()

    # Boîtes de dialogue de démarrage
    host = simpledialog.askstring("Connexion", "Adresse IP / Nom d'hôte du serveur :", initialvalue="127.0.0.1") or "127.0.0.1"
    port_input = simpledialog.askinteger("Connexion", "Port TCP :", initialvalue=8888) or 8888

    client = GameClient(host, port_input)
    try:
        client.connect()
    except OSError as e:
        messagebox.showerror("Connexion impossible", f"Impossible d'ouvrir la socket vers {host}:{port_input} :\n{e}")
        return

    # Vérification d'une session précédente
    has_saved_session = client.load_session("session.json")
    resume_choice = False
    if has_saved_session:
        resume_choice = messagebox.askyesno(
            "Session trouvée",
            f"Une session précédente pour '{client.player_name}' a été trouvée.\nSouhaitez-vous la reprendre (RESUME) ?"
        )

    player_name = client.player_name or "Joueur"
    if not resume_choice:
        player_name = simpledialog.askstring("Identification", "Entrez votre pseudo :", initialvalue="Joueur") or "Joueur"

    root.deiconify()
    app = HangmanApp(root, client)

    if resume_choice:
        app.resume_existing_session()
    else:
        app.start_session(player_name)

    root.protocol("WM_DELETE_WINDOW", lambda: (client.close(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()