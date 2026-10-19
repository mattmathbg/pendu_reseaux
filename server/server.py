import argparse
import asyncio
import random
from typing import Any

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
    def __init__(self, host: str | list[str] | None = None, port: int = 8888) -> None:
        # Par défaut, écoute Dual-Stack en boucle locale (IPv4 et IPv6)
        if host is None:
            self.host = ["127.0.0.1", "::1"]
        else:
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
        """Sérialise, encadre avec \\n et envoie le message."""
        raw = StreamFramer().frame(msg.serialize())
        writer.write(raw)
        await writer.drain()

    async def recv(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Traite le flux TCP pour une connexion client."""
        peer = writer.get_extra_info("peername")
        print(f"[SERVEUR] [CONNEXION] Nouveau client connecté : {peer}")
        framer = StreamFramer()
        current_session: GameSession | None = None

        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    # Fin de flux TCP (le client a fermé la connexion)
                    print(f"[SERVEUR] [DECONNEXION] Fin de flux TCP pour {peer}")
                    break

                framer.feed(chunk)

                while True:
                    msg_bytes = framer.get_next_message()
                    if msg_bytes is None:
                        break

                    try:
                        message_obj = Message.deserialize(msg_bytes)
                        print(f"[SERVEUR] [RECU {peer}] Type={message_obj.type} ReqId={message_obj.request_id} Session={message_obj.session_id} Payload={message_obj.payload}")

                        response, current_session = await self._dispatch_message(
                            message_obj, current_session
                        )
                        print(f"[SERVEUR] [ENVOI {peer}] Type={response.type} ReqId={response.request_id} Payload={response.payload}")
                        await self.send_message(writer, response)

                    except ProtocolError as e:
                        err_response = Message(
                            type="ERROR",
                            request_id=0,
                            payload={"code": "BAD_REQUEST", "message": str(e)}
                        )
                        print(f"[SERVEUR] [ERREUR PROTOCOLE {peer}] {e}")
                        await self.send_message(writer, err_response)

        except ConnectionResetError:
            print(f"[SERVEUR] [COUPURE] Coupure brutale de la connexion client ({peer}).")
        finally:
            if current_session is not None:
                current_session.handle_disconnect()
                print(f"[SERVEUR] [SESSION] Session {current_session.session_id} suspendue (en attente de RESUME sous 60s).")
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
            print(f"[SERVEUR] [IDEMPOTENCE] Cache hit pour request_id={msg.request_id}. Réponse renvoyée sans recalcul.")
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

        if msg.type == "QUIT":
            # La session est supprimée, donc on ne peut plus la renvoyer
            return response, None 
        
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
                payload={"status": "IDLE", "message": "Prêt pour une nouvelle partie."}
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
        payload: dict[str, Any] = {
            "masked_word": game.get_masked_word(),
            "errors_left": game.max_errors - game.current_errors,
            "used_letters": sorted(list(game.guessed_letters)),
            "status": game.state.value,
        }
        if game.is_finished():
            payload["secret_word"] = game.secret_word

        return Message(
            type="STATE",
            request_id=request_id,
            session_id=session.session_id,
            payload=payload,
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
        print(f"[SERVEUR] Serveur Pendu démarré sur : {addrs}")

        try:
            async with server:
                await server.serve_forever()
        finally:
            cleanup_task.cancel()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serveur de Pendu Réseau")
    parser.add_argument("--host", default=None, help="Adresse d'écoute (défaut : dual-stack 127.0.0.1 et ::1)")
    parser.add_argument("--port", type=int, default=8888, help="Port d'écoute TCP (défaut : 8888)")
    args = parser.parse_args()

    srv = Server(host=args.host, port=args.port)
    try:
        asyncio.run(srv.start())
    except KeyboardInterrupt:
        print("\n[SERVEUR] Arrêt du serveur.")