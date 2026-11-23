import json
import os
import socket
import select 
import time 
from typing import Callable
from protocol.framing import StreamFramer
from protocol.message import Message


#------------------------------------------------------------------------------
# SSL/TLS support
#------------------------------------------------------------------------------

import ssl
import sys
from pathlib import Path
SESSION_TTL = 60  


def connect_to_server(endpoints: list[dict], port: int, timeout: float = 5.0) -> socket.socket:
    """Essaie chaque point d'accès annoncé par le serveur, dans l'ordre."""
    last_error: OSError | None = None
    for ep in endpoints:
        try:
            return socket.create_connection((ep["host"], port), timeout=timeout)
        except OSError as exc:
            last_error = exc
    raise ConnectionError(f"Aucun point d'accès joignable : {last_error}")

def create_client_ssl_context(ca_cert_path: str = "certs/server.crt") -> ssl.SSLContext:
    target_path = Path(ca_cert_path)
    if not target_path.exists() and hasattr(sys, "_MEIPASS"):
        alt = Path(sys._MEIPASS) / ca_cert_path
        if alt.exists():
            target_path = alt
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(target_path))
    # Charge le certificat du serveur comme autorité de confiance
    context.load_verify_locations(cafile=str(target_path))
    # Vérifie que le CN correspond (ex: localhost)
    context.check_hostname = True
    return context


class GameClient:
    """
    Client de jeu du Pendu au-dessus de TCP.

    Responsabilités :
    - Établir et maintenir la connexion TCP (IPv4 / IPv6).
    - Encadrer (framing) et sérialiser les messages JSON via StreamFramer.
    - Gérer le cycle de vie de session (HELLO, NEW_GAME, RESUME, QUIT).
    - Assurer la tolérance aux pannes avec retry_last et reconnexion automatique (idempotence).
    """
    def __init__(self, host: str = "127.0.0.1", port: int = 8888, timeout: float = 5.0, use_tls: bool = False) -> None:
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
        self.use_tls: bool = use_tls  # Indique si la connexion doit utiliser TLS/SSL
        self.inbox: list[dict] = []
        self.endpoints: list[dict] = [] 

    def _log(self, direction: str, text: str) -> None:
        if self.log_callback:
            self.log_callback(direction, text)

    def connect(self) -> None:
            """Établit la connexion TCP (IPv4 et IPv6), avec repli sur 127.0.0.1 et TLS optionnel."""
            self.framer = StreamFramer()
            try:
                # Essaie les endpoints annoncés par le serveur, dans l'ordre
                endpoints = self.endpoints or [{"host": self.host}]
                raw_sock = connect_to_server(endpoints, self.port, self.timeout)
            except OSError as e:
                # Repli : si l'adresse réseau échoue (pare-feu, loopback), on tente 127.0.0.1
                if self.host in ("127.0.0.1", "localhost", "::1"):
                    raise
                try:
                    raw_sock = socket.create_connection(("127.0.0.1", self.port), timeout=self.timeout)
                    self._log("CONNEXION", f"Connexion directe à {self.host} échouée, repli sur 127.0.0.1")
                    self.host = "127.0.0.1"
                except OSError:
                    raise e

            if self.use_tls:
                context = create_client_ssl_context()
                # server_hostname doit correspondre au CN/SAN du certificat (localhost)
                hostname = self.host if self.host not in ("127.0.0.1", "::1") else "localhost"
                self.sock = context.wrap_socket(raw_sock, server_hostname=hostname)
                self._log("CONNEXION", f"Connecté à {self.host}:{self.port} via TLS ({self.sock.version()})")
            else:
                self.sock = raw_sock
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

    def new_game(self, player: str | None = None, category_id: int | None = None) -> Message:
        """
        Démarre une nouvelle partie.
        Si un pseudo est fourni et qu'aucune session n'est active, initie HELLO d'abord.
        """
        if player is not None and not self.session_id:
            hello_resp = self.hello(player)
            if hello_resp.type == "ERROR":
                return hello_resp

        payload = {}
        if category_id is not None:
                payload["category_id"] = category_id

        return self.request("NEW_GAME", payload)
    

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
        """Quitte la partie : supprime la session côté serveur et retire l'entrée du fichier."""
        resp = self.request("QUIT")
        self.forget_session()         
        self.session_id = None
        self.auth_token = None
        self.auto_reconnect = False
        return resp

    def forget_session(self, filepath: str = "session.json") -> None:
        """Retire l'entrée du joueur courant."""
        sessions = self._read_sessions(filepath)
        sessions.pop(self.player_name, None)
        self._write_sessions(sessions, filepath)


    def _read_sessions(self, filepath: str = "session.json") -> dict:
        if not os.path.exists(filepath):
            return {}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_sessions(self, sessions: dict, filepath: str = "session.json") -> None:
        if not sessions:
            if os.path.exists(filepath):
                os.remove(filepath)
            return
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(sessions, f, indent=2)

    def save_session(self, filepath: str = "session.json") -> None:
        """Enregistre la session du joueur courant dans la liste indexée par pseudo."""
        sessions = self._read_sessions(filepath)
        now = time.time()
        sessions = {n: e for n, e in sessions.items() if now - e.get("last_seen", 0) <= SESSION_TTL}
        if self.player_name and self.session_id:
            sessions[self.player_name] = {
                "session_id": self.session_id,
                "auth_token": self.auth_token,
                "last_seen": now,
            }
        self._write_sessions(sessions, filepath)
        self._log("INFO", f"Session enregistrée dans {filepath} pour {self.player_name}")

    def load_session(self, pseudo: str | None = None, filepath: str = "session.json") -> bool:
        """Charge une session par pseudo. Sans pseudo, prend l'entrée si elle est unique."""
        sessions = self._read_sessions(filepath)
        if pseudo is None and len(sessions) == 1:
            pseudo = next(iter(sessions))
        entry = sessions.get(pseudo) if pseudo else None
        if not entry or time.time() - entry.get("last_seen", 0) > SESSION_TTL:
            return False
        self.player_name = pseudo
        self.session_id = entry["session_id"]
        self.auth_token = entry["auth_token"]
        return bool(self.session_id and self.auth_token)

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
                    self.last_message = msg
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
              raise ConnectionError("Pas de connexion active")

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
        """
        Lit le réseau jusqu'à recevoir la réponse à la requête en cours.

        Les pushs (CHAT avec request_id 0) rencontrés en route sont rangés dans
        `inbox` et ignorés : ils ne sont pas la réponse attendue.
        Bloquant : utilisé uniquement par request() / retry_last().
        """
        while True:
            # 1. Un message complet est-il déjà dans le framer ?
            raw = self.framer.get_next_message()
            if raw is None:
                # 2. Sinon, on attend de nouveaux octets sur la socket (bloquant)
                chunk = self.sock.recv(4096)
                if not chunk:
                    # recv() renvoie b"" quand le serveur a fermé la connexion
                    raise ConnectionError("Le serveur a fermé la connexion")
                self.framer.feed(chunk)
                continue

            # 3. Un message complet est disponible : on le désérialise et on le trie
            msg = Message.deserialize(raw)
            if self._store_if_push(msg):
                continue  # c'était un push : on le garde, on continue à lire
            return msg  # c'est la réponse attendue


    def _store_if_push(self, msg: Message) -> bool:
        """
        Range le message dans `inbox` s'il s'agit d'un push du serveur.

        Un push est un CHAT avec request_id == 0 : le serveur l'envoie aux autres
        joueurs sans qu'ils l'aient demandé. Le compteur du client commence à 1,
        donc aucune vraie réponse ne peut avoir 0 : ce numéro suffit à les distinguer.

        Renvoie True si le message a été rangé (c'est un push), False sinon.
        """
        if msg.type == "CHAT" and msg.request_id == 0:
            self.inbox.append(msg.payload)
            return True
        return False


    def poll(self) -> None:
        """
        Lit ce qui est déjà arrivé sur la socket, sans jamais attendre.

        Appelée régulièrement par l'interface (toutes les 200 ms) pour afficher
        les messages des autres joueurs, même quand le joueur ne fait rien.
        Les messages reçus sont rangés dans `inbox` via _store_if_push.
        """
        if self.sock is None:
            return

        # Traite d'abord ce qui est déjà dans le framer (un message peut y être resté
        # d'une lecture précédente, sans nouvelle donnée sur la socket)
        self._process_buffered()

        while True:
            # En TLS, OpenSSL peut avoir déjà déchiffré des octets que select() ne voit pas.
            # pending() indique s'il en reste à lire.
            has_pending = hasattr(self.sock, "pending") and self.sock.pending() > 0
            if not has_pending:
                # select avec délai 0 : demande au système si des données sont prêtes,
                # sans attendre. Si rien n'est prêt, on sort immédiatement.
                readable, _, _ = select.select([self.sock], [], [], 0)
                if not readable:
                    break

            # Des données sont disponibles : recv ne bloquera pas
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Le serveur a fermé la connexion")
            self.framer.feed(chunk)
            self._process_buffered()


    def _process_buffered(self) -> None:
        """
        Extrait tous les messages complets du framer et les trie.

        Un bloc reçu peut contenir plusieurs messages, ou seulement le début d'un
        message : le framer ne rend que les messages complets, un par un.
        Un message qui n'est pas un push, reçu hors requête, est signalé dans les logs.
        """
        while True:
            raw = self.framer.get_next_message()
            if raw is None:
                break  # plus de message complet : on attend la suite
            msg = Message.deserialize(raw)
            if not self._store_if_push(msg):
                self._log("ERREUR", f"Réponse inattendue hors requête : {msg.type}")


    def chat(self, text: str, scope: str = "global") -> Message:
        """
        Envoie un message de chat.

        scope : "global" (tous les joueurs) ou "room" (seulement le salon courant).
        Renvoie la réponse du serveur (CHAT avec le request_id de cette requête).
        """
        return self.request("CHAT", {"text": text, "scope": scope})


    def join_room(self, room: str) -> Message:
        """Rejoint le salon `room`. Renvoie ROOM, ou ERROR si le nom est invalide."""
        return self.request("JOIN_ROOM", {"room": room})


    def leave_room(self) -> Message:
        """Quitte le salon courant. Renvoie ROOM (room_id = None) ou ERROR."""
        return self.request("LEAVE_ROOM")


    

    