from client.connection import GameClient
from protocol.message import Message


class GameController:
    """Logique du client : parle au serveur, ne touche jamais à l'écran."""

    def __init__(self, client: GameClient) -> None:
        self.client = client

    def join_room(self, room_name: str) -> Message:
        return self.client.join_room(room_name)

    def leave_room(self) -> Message:
        return self.client.leave_room()

    def chat(self, text: str, scope: str) -> Message:
        return self.client.chat(text, scope)

    def poll(self) -> list[dict]:
        """Relit le réseau sans bloquer et renvoie les messages reçus sans demande."""
        self.client.poll()
        messages = list(self.client.inbox)
        self.client.inbox.clear()
        return messages

    def guess(self, letter: str) -> Message:
        return self.client.guess(letter)

    def new_game(self) -> Message:
        return self.client.new_game()

    def quit_game(self) -> Message:
        return self.client.quit_game()

    def connect(self, host: str, port: int, pseudo: str) -> Message:
        """Ouvre la connexion puis fait HELLO. Renvoie la réponse (WELCOME ou ERROR)."""
        self.client.host = host
        self.client.port = port
        self.client.connect()
        return self.client.hello(pseudo)

    def resume(self, host: str, port: int) -> Message:
        """Rouvre la connexion si besoin, puis reprend la session par RESUME."""
        self.client.host = host
        self.client.port = port
        if not self.client.is_connected():
            self.client.connect()
        return self.client.resume()