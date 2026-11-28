"""
Règles d'une partie en duel (1 contre 1, tour par tour).

Un duel a un mot commun, des erreurs communes et un tour qui alterne
à chaque lettre proposée.
"""

from core.pendu import GameState, Pendu, InvalidLetterError, LetterAlreadyTriedError, InvalidStateError

FORFAIT_DELAY = 60  # secondes accordées à un joueur déconnecté pour revenir


class DuelError(Exception):
    """Action refusée dans le duel. `code` correspond au code d'erreur du protocole."""

    def __init__(self, code: str, message: str) -> None:
        """Conserve le code protocolaire et le message explicatif de l'erreur."""
        super().__init__(message)
        self.code = code
        self.message = message


class Duel:
    """Gère l'état d'un duel à deux joueurs et les règles communes de la partie."""

    def __init__(self, duel_id: str, creator, secret_word: str, max_errors: int = 6) -> None:
        """Crée un duel en attente avec le mot secret et le joueur créateur."""
        # creator : la GameSession du créateur
        self.duel_id = duel_id
        self.players = [creator]          # sessions, dans l'ordre d'arrivée
        self.status = "EN_ATTENTE"        # EN_ATTENTE -> EN_COURS -> TERMINE
        self.turn_index = 0               # index dans players : à qui c'est le tour
        self.game = Pendu(secret_word=secret_word, max_errors=max_errors)
        self.winner = None                # pseudo du gagnant une fois TERMINE
        self.reason = None                # "victoire", "défaite" ou "forfait"

    # --- Joueurs ---

    def add_player(self, session) -> None:
        """Ajoute le second joueur. Démarre la partie. Refuse si le duel est plein."""
        if len(self.players) >= 2:
            raise DuelError("INVALID_STATE", "Le duel est complet.")
        if self.status != "EN_ATTENTE":
            raise DuelError("INVALID_STATE", "Le duel n'accepte plus de joueurs.")
        self.players.append(session)
        self.status = "EN_COURS"          # le créateur joue en premier (index 0)

    def has_player(self, session) -> bool:
        """Indique si la session appartient déjà à ce duel."""
        return any(p is session for p in self.players)

    @property
    def current_player(self):
        """Retourne la session autorisée à jouer au tour courant."""
        return self.players[self.turn_index]

    @property
    def player_names(self) -> list[str]:
        """Retourne les pseudos des joueurs participants."""
        return [p.player_name for p in self.players]

    @property
    def turn_name(self) -> str | None:
        """Retourne le pseudo du joueur actif ou None lorsque le duel est arrêté."""
        return self.current_player.player_name if self.status == "EN_COURS" else None

    # --- Coup ---

    def play(self, session, letter: str) -> None:
        """Joue une lettre pour `session`. Refuse si ce n'est pas son tour."""
        if self.status != "EN_COURS":
            raise DuelError("INVALID_STATE", "La partie n'est pas en cours.")
        if session is not self.current_player:
            raise DuelError("NOT_YOUR_TURN", "Ce n'est pas votre tour.")
        try:
            self.game.guess(letter)
        except (InvalidLetterError, LetterAlreadyTriedError) as exc:
            raise DuelError("INVALID_LETTER", str(exc))
        except InvalidStateError as exc:
            raise DuelError("INVALID_STATE", str(exc))

        if self.game.state == GameState.WON:
            self._finish(winner=session, reason="victoire")
        elif self.game.state == GameState.LOST:
            self._finish(winner=None, reason="défaite")
        else:
            # Le tour passe à l'autre joueur, que la lettre soit juste ou fausse
            self.turn_index = (self.turn_index + 1) % len(self.players)

    def _finish(self, winner, reason: str) -> None:
        """Marque le duel terminé avec son vainqueur éventuel et la raison."""
        self.status = "TERMINE"
        self.winner = winner.player_name if winner else None
        self.reason = reason

    # --- Forfait ---

    def forfeit_if_absent(self, now: float) -> bool:
        """
        Si un joueur est absent depuis plus de FORFAIT_DELAY secondes,
        l'autre gagne. Renvoie True si le duel vient de se terminer.
        """
        if self.status != "EN_COURS":
            return False
        for leaver in self.players:
            if leaver.is_connected or leaver.disconnect_timestamp is None:
                continue
            if now - leaver.disconnect_timestamp <= FORFAIT_DELAY:
                continue
            others = [p for p in self.players if p is not leaver]
            self._finish(winner=others[0], reason="forfait")
            return True
        return False

    # --- Projection pour le réseau ---

    def to_payload(self) -> dict:
        """Données envoyées au client (aucun secret : le mot n'apparaît pas tant que la partie est en cours)."""
        payload = {
            "duel_id": self.duel_id,
            "status": self.status,
            "players": self.player_names,
            "turn": self.turn_name,
            "masked_word": self.game.get_masked_word(),
            "errors_left": self.game.max_errors - self.game.current_errors,
            "max_errors": self.game.max_errors,
            "used_letters": sorted(self.game.guessed_letters),
        }
        if self.status == "TERMINE":
            payload["winner"] = self.winner
            payload["reason"] = self.reason
            payload["secret_word"] = self.game.secret_word
        return payload