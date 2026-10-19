import asyncio
import random

from core.pendu import (
    Pendu,
    InvalidLetterError,
    LetterAlreadyTriedError,
    InvalidStateError,
)
from core.session import GameSession, SessionManager
from protocol.framing import StreamFramer
from protocol.message import Message, ProtocolError
from server.dispatcher import MessageDispatcher


def mot_aleatoire() -> str:
    """Retourne un mot aléatoire pour une manche."""
    mots = ["PYTHON", "ASYNCHRONE", "SOCKET", "SERVEUR", "PROTOCOLE", "RESEAUX"]
    return random.choice(mots)


class Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 8888) -> None:
        self.host = host
        self.port = port
        self.sessions = SessionManager(timeout=60)
        self.dispatcher = MessageDispatcher()

        # Enregistrement dynamique des actions de jeu sur le dispatcher
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Enregistre les méthodes associées aux actions de jeu."""
        self.dispatcher.register("NEW_GAME")(self._handle_new_game)
        self.dispatcher.register("LETTER")(self._handle_letter)
        self.dispatcher.register("QUIT")(self._handle_quit)

    async def send_message(self, writer: asyncio.StreamWriter, msg: Message) -> None:
        """Sérialise, encadre avec \n et envoie le message."""
        writer.write(StreamFramer().frame(msg.serialize()))
        await writer.drain()

    async def recv(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Traite le flux TCP pour une connexion client."""
        framer = StreamFramer()
        current_session: GameSession | None = None

        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    # Fin de flux TCP (le client s'est déconnecté)
                    break

                framer.feed(chunk)

                while True:
                    msg_bytes = framer.get_next_message()
                    if msg_bytes is None:
                        break

                    try:
                        message_obj = Message.deserialize(msg_bytes)
                        response, current_session = await self._dispatch_message(
                            message_obj, current_session
                        )
                        await self.send_message(writer, response)

                    except ProtocolError as e:
                        err_response = Message(
                            type="ERROR",
                            request_id=0,
                            payload={"code": "BAD_REQUEST", "message": str(e)}
                        )
                        await self.send_message(writer, err_response)

        except ConnectionResetError:
            print("Coupure brutale du client.")
        finally:
            if current_session is not None:
                current_session.handle_disconnect()
                print(f"Session {current_session.session_id} suspendue (en attente de RESUME).")
            writer.close()
            await writer.wait_closed()

    async def _dispatch_message(
        self, msg: Message, current_session: GameSession | None
    ) -> tuple[Message, GameSession | None]:
        """Aiguille le message, contrôle l'authentification et l'idempotence."""
        # 1. Commandes hors session (connexion / reconnexion)
        if msg.type == "HELLO":
            return await self._handle_hello(msg)

        if msg.type == "RESUME":
            return await self._handle_resume(msg)

        # 2. Vérification de l'existence de la session
        if current_session is None and msg.session_id:
            current_session = self.sessions.get_session(msg.session_id)

        if current_session is None:
            err = Message(
                type="ERROR",
                request_id=msg.request_id,
                payload={"code": "UNAUTHORIZED", "message": "Session inconnue ou expirée"}
            )
            return err, None

        # 3. Vérification d'idempotence (requête déjà traitée)
        cached = current_session.get_cached_response(msg.request_id)
        if cached is not None:
            if isinstance(cached, bytes):
                return Message.deserialize(cached), current_session
            if isinstance(cached, dict):
                return Message(
                    type=cached.get("type", "STATE"),
                    request_id=msg.request_id,
                    session_id=current_session.session_id,
                    payload=cached.get("payload", cached),
                ), current_session
            return cached, current_session

        # 4. Traitement par le dispatcher
        response = await self.dispatcher.dispatch(msg, current_session)

        # 5. Sauvegarde pour l'idempotence
        current_session.save_response(msg.request_id, response)

        return response, current_session

    async def _handle_hello(self, msg: Message) -> tuple[Message, GameSession]:
        player_name = msg.payload.get("player_name", "Anonyme")
        session = self.sessions.create_session(player_name)
        response = Message(
            type="WELCOME",
            request_id=msg.request_id,
            session_id=session.session_id,
            payload={
                "session_id": session.session_id,
                "auth_token": session.auth_token,
                "player_name": session.player_name,
            },
        )
        return response, session

    async def _handle_resume(self, msg: Message) -> tuple[Message, GameSession | None]:
        session_id = msg.session_id
        auth_token = msg.payload.get("auth_token", "")

        if not session_id:
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                payload={"code": "BAD_REQUEST", "message": "session_id manquant pour RESUME"}
            ), None

        session = self.sessions.get_session(session_id)
        if session is None or not session.reconnect(auth_token):
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session_id,
                payload={"code": "UNAUTHORIZED", "message": "Token invalide ou session expirée"}
            ), None

        # Reconnexion validée : on renvoie le STATE courant si une partie existe
        if session.game:
            response = self._build_state_message(msg.request_id, session)
        else:
            response = Message(
                type="STATE",
                request_id=msg.request_id,
                session_id=session.session_id,
                payload={"status": "idle", "message": "Prêt pour une nouvelle partie."}
            )
        return response, session

    async def _handle_new_game(self, msg: Message, session: GameSession) -> Message:
        secret = mot_aleatoire()
        session.game = Pendu(secret_word=secret, max_errors=6)
        return self._build_state_message(msg.request_id, session)

    async def _handle_letter(self, msg: Message, session: GameSession) -> Message:
        if session.game is None:
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session.session_id,
                payload={
                    "code": "NO_GAME",
                    "message": "Aucune partie lancée. Envoyez NEW_GAME.",
                },
            )

        letter = msg.payload.get("letter", "")
        try:
            session.game.guess(letter)
            return self._build_state_message(msg.request_id, session)
        except (
            InvalidLetterError,
            LetterAlreadyTriedError,
            InvalidStateError,
        ) as exc:
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session.session_id,
                payload={"code": "INVALID_MOVE", "message": str(exc)},
            )

    async def _handle_quit(self, msg: Message, session: GameSession) -> Message:
        self.sessions.remove_session(session.session_id)
        return Message(
            type="BYE",
            request_id=msg.request_id,
            session_id=session.session_id,
            payload={"message": "Session fermée avec succès."}
        )

    def _build_state_message(self, request_id: int, session: GameSession) -> Message:
        game = session.game
        return Message(
            type="STATE",
            request_id=request_id,
            session_id=session.session_id,
            payload={
                "masked_word": game.get_masked_word(),
                "errors_left": game.max_errors - game.current_errors,
                "used_letters": sorted(list(game.guessed_letters)),
                "status": game.state.value,
            },
        )

    async def _cleanup_loop(self) -> None:
        """Tâche de fond qui nettoie périodiquement les sessions expirées."""
        while True:
            await asyncio.sleep(10)
            self.sessions.clean_expired_sessions()

    async def start(self) -> None:
        """Démarre le serveur TCP asynchrone."""
        # Lancement de la tâche de nettoyage
        cleanup_task = asyncio.create_task(self._cleanup_loop())

        server = await asyncio.start_server(self.recv, self.host, self.port)
        addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
        print(f"Serveur Pendu démarré sur {addrs}")

        try:
            async with server:
                await server.serve_forever()
        finally:
            cleanup_task.cancel()


if __name__ == "__main__":
    srv = Server(host="127.0.0.1", port=8888)
    try:
        asyncio.run(srv.start())
    except KeyboardInterrupt:
        print("\nArrêt du serveur.")