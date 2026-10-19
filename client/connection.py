import json
import os
import socket
from typing import Callable
from protocol.framing import StreamFramer
from protocol.message import Message


class GameClient:
    """
    Client de jeu du Pendu au-dessus de TCP.
    
    Responsabilités :
    - Établir et maintenir la connexion TCP (IPv4 / IPv6).
    - Encadrer (framing) et sérialiser les messages JSON via StreamFramer.
    - Gérer le cycle de vie de session (HELLO, NEW_GAME, RESUME, QUIT).
    - Assurer la tolérance aux pannes avec retry_last et reconnexion automatique (idempotence).
    """
    def __init__(self, host: str = "127.0.0.1", port: int = 8888, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.framer = StreamFramer()
        self.next_request_id = 1
        self.session_id: str | None = None
        self.auth_token: str | None = None
        self.player_name: str | None = None
        self.last_message: Message | None = None
        self.auto_reconnect: bool = False
        self.log_callback: Callable[[str, str], None] | None = None

    def _log(self, direction: str, text: str) -> None:
        if self.log_callback:
            self.log_callback(direction, text)

    def connect(self) -> None:
        """Établit la connexion TCP (supporte nativement IPv4 et IPv6)."""
        self.framer = StreamFramer()
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._log("CONNEXION", f"Connecté à {self.host}:{self.port}")

    def close(self) -> None:
        """Ferme la socket TCP proprement."""
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
            self._log("CONNEXION", "Socket fermée.")

    def is_connected(self) -> bool:
        """Indique si la socket est actuellement connectée."""
        return self.sock is not None

    def hello(self, player_name: str) -> Message:
        """
        Envoie le message HELLO pour s'enregistrer et obtenir une session.
        Stocke session_id et auth_token dès réception de WELCOME.
        """
        self.player_name = player_name
        resp = self.request("HELLO", {"player_name": player_name})
        if resp.type == "WELCOME":
            self.session_id = resp.payload.get("session_id", resp.session_id)
            self.auth_token = resp.payload.get("auth_token")
            self.auto_reconnect = True
        return resp

    def new_game(self, player: str | None = None) -> Message:
        """
        Démarre une nouvelle partie.
        Si un pseudo est fourni et qu'aucune session n'est active, initie HELLO d'abord.
        """
        if player is not None and not self.session_id:
            hello_resp = self.hello(player)
            if hello_resp.type == "ERROR":
                return hello_resp
        return self.request("NEW_GAME")

    def guess(self, letter: str) -> Message:
        """Propose une lettre au serveur."""
        return self.request("LETTER", {"letter": letter})

    def resume(self, session_id: str | None = None, auth_token: str | None = None) -> Message:
        """
        Reprend une session existante après une coupure.
        Envoie RESUME avec auth_token et reçoit l'état courant (STATE).
        """
        if session_id:
            self.session_id = session_id
        if auth_token:
            self.auth_token = auth_token

        resp = self.request("RESUME", {"auth_token": self.auth_token})
        if resp.type == "STATE":
            self.auto_reconnect = True
        return resp

    def quit_game(self) -> Message:
        """Quitte la partie et détruit la session sur le serveur."""
        resp = self.request("QUIT")
        self.session_id = None
        self.auth_token = None
        self.auto_reconnect = False
        return resp

    def save_session(self, filepath: str = "session.json") -> None:
        """Sauvegarde les jetons de session dans un fichier JSON pour reprise ultérieure."""
        data = {
            "host": self.host,
            "port": self.port,
            "player_name": self.player_name,
            "session_id": self.session_id,
            "auth_token": self.auth_token,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self._log("INFO", f"Session enregistrée dans {filepath}")

    def load_session(self, filepath: str = "session.json") -> bool:
        """Charge les jetons d'une session sauvegardée."""
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.host = data.get("host", self.host)
            self.port = data.get("port", self.port)
            self.player_name = data.get("player_name", self.player_name)
            self.session_id = data.get("session_id")
            self.auth_token = data.get("auth_token")
            loaded = bool(self.session_id and self.auth_token)
            if loaded:
                self._log("INFO", f"Session chargée depuis {filepath} (ID: {self.session_id})")
            return loaded
        except Exception:
            return False

    def request(self, msg_type: str, payload: dict | None = None) -> Message:
        """
        Envoie une requête au serveur et attend la réponse sérialisée.
        Incrémente next_request_id et conserve la requête pour l'idempotence.
        En cas de coupure réseau, tente automatiquement de se reconnecter
        et de rejouer la requête via retry_last().
        """
        msg = Message(
            type=msg_type,
            request_id=self.next_request_id,
            session_id=self.session_id,
            payload=payload or {},
        )
        self.next_request_id += 1
        self.last_message = msg

        try:
            return self._send_and_wait(msg)
        except (ConnectionError, OSError) as e:
            # Reconnexion transparente seulement si session active et requête métier
            if (
                self.auto_reconnect
                and self.session_id
                and self.auth_token
                and msg_type not in ("HELLO", "RESUME", "QUIT")
            ):
                self._log(
                    "RECONNEXION",
                    f"Coupure détectée ({e}). Tentative de reconnexion et RESUME...",
                )
                try:
                    self.close()
                    self.connect()
                    resume_resp = self.resume(self.session_id, self.auth_token)
                    if resume_resp.type == "ERROR":
                        raise ConnectionError(
                            f"Échec RESUME : {resume_resp.payload.get('message')}"
                        )

                    self._log(
                        "RECONNEXION",
                        f"Session restaurée. Renvoi de la requête (idempotence id={msg.request_id})...",
                    )
                    return self.retry_last()
                except Exception as rec_err:
                    self._log("ERREUR", f"Échec reconnexion automatique : {rec_err}")
                    raise
            raise

    def retry_last(self) -> Message:
        """Renvoie la dernière requête avec le MÊME request_id (idempotence)."""
        if self.last_message is None:
            raise ValueError("Aucune dernière requête à renvoyer.")
        return self._send_and_wait(self.last_message)

    def _send_and_wait(self, msg: Message) -> Message:
        """Envoi bas-niveau avec encadrement framing et lecture bloquante."""
        if self.sock is None:
            self.connect()

        raw_bytes = self.framer.frame(msg.serialize())
        self._log(
            "ENVOI",
            f"Trame ({len(raw_bytes)} octets) : {raw_bytes.decode('utf-8', errors='replace').strip()}",
        )
        self.sock.sendall(raw_bytes)
        resp = self._read_message()
        self._log(
            "REÇU",
            f"Type={resp.type} ReqId={resp.request_id} Session={resp.session_id} Payload={resp.payload}",
        )
        return resp

    def _read_message(self) -> Message:
        """Lit le réseau jusqu'à extraire un message complet délimité par \\n."""
        while True:
            raw = self.framer.get_next_message()
            if raw is not None:
                return Message.deserialize(raw)
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Le serveur a fermé la connexion")
            self.framer.feed(chunk)