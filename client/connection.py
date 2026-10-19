import socket
from protocol.framing import StreamFramer
from protocol.message import Message


class GameClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 8888) -> None:
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.framer = StreamFramer()      # un framer par connexion
        self.next_request_id = 1          # compteur : 1, 2, 3...
        self.session_id: str | None = None
        self.last_message: Message | None = None

    def connect(self) -> None:
        # fonctionne en IPv4 ("127.0.0.1") comme en IPv6 ("::1")
        self.framer = StreamFramer()
        self.sock = socket.create_connection((self.host, self.port), timeout=5)

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None

    def request(self, msg_type, payload=None) -> Message:
        msg = Message(
            type=msg_type,
            request_id=self.next_request_id,
            session_id=self.session_id,
            payload=payload or {},
        )
        self.next_request_id += 1
        self.last_message = msg          # on garde le message pour pouvoir le renvoyer
        return self._send_and_wait(msg)

    def retry_last(self) -> Message:
        """Renvoie la dernière requête avec le MÊME request_id."""
        return self._send_and_wait(self.last_message)

    def _send_and_wait(self, msg: Message) -> Message:
        self.sock.sendall(self.framer.frame(msg.serialize()))
        return self._read_message()

    def _read_message(self) -> Message:
        """Lit le réseau jusqu'à avoir un message complet."""
        while True:
            raw = self.framer.get_next_message()   # y a-t-il déjà un message complet ?
            if raw is not None:
                return Message.deserialize(raw)
            chunk = self.sock.recv(4096)           # sinon on lit le réseau
            if not chunk:
                raise ConnectionError("Le serveur a fermé la connexion")
            self.framer.feed(chunk)