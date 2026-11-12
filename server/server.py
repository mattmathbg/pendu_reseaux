import argparse
import asyncio
from csv import writer
import random
from typing import Any


from core import pendu
from core.pendu import (
    Pendu,
    InvalidLetterError,
    LetterAlreadyTriedError,
    InvalidStateError,
)
from core.session import GameSession, SessionManager
from protocol.framing import StreamFramer
from protocol.message import Message, ProtocolError
from protocol.discovery import DiscoveryServer, DEFAULT_DISCOVERY_PORT
from server.dispatcher import MessageDispatcher


def mot_aleatoire() -> str:
    """Retourne un mot aléatoire pour une manche."""
    mots = ["PYTHON", "ASYNCHRONE", "SOCKET", "SERVEUR", "PROTOCOLE", "RESEAUX"]
    return random.choice(mots)

#---------------------------------------------------------------------
# SSL/TLS
#---------------------------------------------------------------------

import ssl
from pathlib import Path

def create_server_ssl_context(cert_dir: str = "certs") -> ssl.SSLContext:
    path = Path(cert_dir)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(
        certfile=str(path / "server.crt"),
        keyfile=str(path / "server.key")
    )
    return context

class Server:
    def __init__(
        self,
        host: str | list[str] | None = None,
        port: int = 8888,
        use_tls: bool = False,
        server_name: str = "Serveur Pendu M1",
        enable_discovery: bool = True,
    ) -> None:
        # Par défaut, écoute Dual-Stack en boucle locale (IPv4 et IPv6)
        if host is None:
            self.host = ["127.0.0.1", "::1"]
        else:
            self.host = host
        self.port = port
        self.sessions = SessionManager(timeout=60)
        self.dispatcher = MessageDispatcher()
        self.use_tls = use_tls  # Indique si le serveur doit utiliser TLS/SSL
        self.server_name = server_name
        self.enable_discovery = enable_discovery

        # Service d'annonce Multicast UDP
        if self.enable_discovery:
            self.discovery_server: DiscoveryServer | None = DiscoveryServer(
                tcp_port=self.port,
                server_name=self.server_name,
                use_tls=self.use_tls,
                get_players_count=lambda: len(self.sessions.sessions),
            )
        else:
            self.discovery_server = None

        # Enregistrement dynamique des actions de jeu sur le dispatcher
        self._register_handlers()



    def _register_handlers(self) -> None:
        """Enregistre les méthodes associées aux actions de jeu."""
        self.dispatcher.register("NEW_GAME")(self._handle_new_game)
        self.dispatcher.register("LETTER")(self._handle_letter)
        self.dispatcher.register("QUIT")(self._handle_quit)
        self.dispatcher.register("JOIN_ROOM")(self._handle_join_room)
        self.dispatcher.register("LEAVE_ROOM")(self._handle_leave_room)
        self.dispatcher.register("CHAT")(self._handle_chat)

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
                    try:
                        msg_bytes = framer.get_next_message()
                    except ProtocolError as e:
                        err_response = Message(
                            type="ERROR",
                            request_id=0,
                            payload={"code": "INVALID_MESSAGE", "message": str(e)},
                        )
                        print(f"[SERVEUR] [ERREUR PROTOCOLE {peer}] {e}")
                        await self.send_message(writer, err_response)
                        return
                    if msg_bytes is None:
                        break

                    try:
                        message_obj = None
                        message_obj = Message.deserialize(msg_bytes)
                        print(f"[SERVEUR] [RECU {peer}] Type={message_obj.type} ReqId={message_obj.request_id} Session={message_obj.session_id} Payload={message_obj.payload}")

                        response, current_session = await self._dispatch_message(
                            message_obj, current_session
                        )
                        if message_obj.type in ("HELLO", "RESUME") and response.type != "ERROR":
                             current_session.owner = writer
                        print(f"[SERVEUR] [ENVOI {peer}] Type={response.type} ReqId={response.request_id} Payload={response.payload}")
                        await self.send_message(writer, response)

                    except ProtocolError as e:
                            err_response = Message(
                                type="ERROR",
                                request_id=0,
                                payload={"code": "INVALID_MESSAGE", "message": str(e)}
                            )
                            print(f"[SERVEUR] [ERREUR PROTOCOLE {peer}] {e}")
                            await self.send_message(writer, err_response)
                    except ConnectionError:
                        raise
                    except Exception as e:
                        err_response = Message(
                            type="ERROR",
                            request_id=message_obj.request_id if message_obj is not None else 0,
                            session_id=current_session.session_id if current_session else None,
                            payload={"code": "INTERNAL_ERROR", "message": "Erreur interne du serveur."}
                        )
                        print(f"[SERVEUR] [ERREUR INTERNE {peer}] {e!r}")
                        await self.send_message(writer, err_response)
                     

        except ConnectionError:
            print(f"[SERVEUR] [COUPURE] Connexion client interrompue ({peer}).")
        finally:
            if current_session is not None and current_session.owner is writer:
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
            if current_session is not None:
                return (
                    Message(
                        type="ERROR",
                        request_id=msg.request_id,
                        session_id=current_session.session_id,
                        payload={
                            "code": "INVALID_STATE",
                            "message": "Une session est déjà active sur cette connexion. "
                                       "Envoyez QUIT avant de renvoyer HELLO.",
                        },
                    ),
                    current_session,   # la connexion garde sa session
                )
            return await self._handle_hello(msg)

        if msg.type == "RESUME":
            return await self._handle_resume(msg)

    
        if current_session is None:
            err = Message(
                type="ERROR",
                request_id=msg.request_id,
                payload={"code": "UNKNOWN_SESSION", "message": "Session inconnue ou expirée"}
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
                payload={"code": "INVALID_MESSAGE", "message": "session_id manquant pour RESUME"}
            ), None

        session = self.sessions.get_session(session_id)
        if session is None :
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session_id,
                payload={"code": "UNKNOWN_SESSION", "message": "Session expirée ou inconnue"}
            ), None

        if not session.reconnect(auth_token):
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session_id,
                payload={"code": "PLAYER_NOT_ALLOWED", "message": "Token invalide"}
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
        if session.game is None or session.game.is_finished():
            session.game = Pendu(secret_word=secret, max_errors=6)
        else:
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session.session_id,
                payload={"code": "INVALID_STATE", "message": "Une partie est déjà en cours."}
            )
        return self._build_state_message(msg.request_id, session)

    async def _handle_letter(self, msg: Message, session: GameSession) -> Message:
        if session.game is None:
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session.session_id,
                payload={
                    "code": "INVALID_STATE",
                    "message": "Aucune partie lancée. Envoyez NEW_GAME.",
                },
            )

        letter = msg.payload.get("letter", "")
        try:
            session.game.guess(letter)
            return self._build_state_message(msg.request_id, session)
        except (InvalidLetterError, LetterAlreadyTriedError) as exc:
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session.session_id,
                payload={"code": "INVALID_LETTER", "message": str(exc)},
            )
        except InvalidStateError as exc:
            return Message( 
                    type="ERROR",
                    request_id=msg.request_id,
                    session_id=session.session_id,
                    payload={"code": "INVALID_STATE", "message": str(exc)},
                        )

    async def _handle_quit(self, msg: Message, session: GameSession) -> Message:
        if session.game and not session.game.is_finished():
            session.game.abandon()
        self.sessions.remove_session(session.session_id)
        return Message(
            type="BYE",
            request_id=msg.request_id,
            session_id=session.session_id,
            payload={
                "message": "Session fermée avec succès.",
                "status": session.game.state.value if session.game else None,
            },
        )

    def _build_state_message(self, request_id: int, session: GameSession) -> Message:
        game = session.game
        payload: dict[str, Any] = {
            "masked_word": game.get_masked_word(),
            "errors_left": game.max_errors - game.current_errors,
            "used_letters": sorted(list(game.guessed_letters)),
            "status": game.state.value,
            "max_errors": game.max_errors,
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
        """Démarre le serveur TCP asynchrone et le répondeur de découverte."""
        # Lancement de la tâche de nettoyage
        cleanup_task = asyncio.create_task(self._cleanup_loop())

        # Démarrage du répondeur UDP Multicast
        if self.discovery_server:
            self.discovery_server.start()

        ssl_context = create_server_ssl_context() if self.use_tls else None
    
        server = await asyncio.start_server(self.recv, self.host, self.port, ssl=ssl_context)
        addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
        print(f"[SERVEUR] Serveur Pendu démarré sur : {addrs}")

        try:
            async with server:
                await server.serve_forever()
        finally:
            cleanup_task.cancel()
            if self.discovery_server:
                self.discovery_server.stop()

    async def _push(self, target_session: GameSession, msg: Message) -> None:
            """Envoie msg à la connexion de target_session, sans jamais bloquer les autres."""
            if target_session.owner is None or not target_session.is_connected:
                return
            try:
                await self.send_message(target_session.owner, msg)
            except (ConnectionError, OSError):
                pass

    async def _handle_join_room(self, msg: Message, session: GameSession) -> Message:
        room = msg.payload.get("room")
        if not isinstance(room, str) or not (1 <= len(room) <= 20):
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session.session_id,
                payload={"code": "INVALID_MESSAGE",
                        "message": "Le nom du salon doit contenir entre 1 et 20 caractères."},
            )
        session.room_id = room
        return Message(
            type="ROOM",
            request_id=msg.request_id,
            session_id=session.session_id,
            payload={"room_id": room, "message": f"Vous avez rejoint le salon {room}."},
        )

    async def _handle_leave_room(self, msg: Message, session: GameSession) -> Message:
        session.room_id = None
        return Message(
            type="ROOM",
            request_id=msg.request_id,
            session_id=session.session_id,
            payload={"room_id": None, "message": "Vous avez quitté le salon."},
        )


    async def _handle_chat(self, msg: Message, session: GameSession) -> Message:
        text = msg.payload.get("text")
        if not isinstance(text, str) or not (1 <= len(text.strip()) <= 200):
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session.session_id,
                payload={"code": "INVALID_MESSAGE",
                        "message": "Le message doit contenir entre 1 et 200 caractères."},
            )
        text = text.strip()

        scope = msg.payload.get("scope")
        if scope not in ("global", "room"):
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session.session_id,
                payload={"code": "INVALID_MESSAGE",
                        "message": "Le scope doit être 'global' ou 'room'."},
            )
        if scope == "room" and session.room_id is None:
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session.session_id,
                payload={"code": "INVALID_STATE",
                        "message": "Vous n'êtes dans aucun salon."},
            )

        # Message poussé aux autres : request_id 0, ce n'est pas une réponse
        push = Message(
            type="CHAT",
            request_id=0,
            payload={"player": session.player_name, "scope": scope,
                    "room_id": session.room_id, "text": text},
        )

        for other in list(self.sessions.sessions.values()):
            if other is session or not other.is_connected:
                continue
            if scope == "room" and other.room_id != session.room_id:
                continue
            await self._push(other, push)

        # Réponse à l'expéditeur : son request_id
        return Message(
            type="CHAT",
            request_id=msg.request_id,
            session_id=session.session_id,
            payload=push.payload,
        )


     
           


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serveur de Pendu Réseau")
    parser.add_argument("--host", default=None, help="Adresse d'écoute (défaut : dual-stack 127.0.0.1 et ::1)")
    parser.add_argument("--port", type=int, default=8888, help="Port d'écoute TCP (défaut : 8888)")
    parser.add_argument("--tls", action="store_true", help="Activer TLS/SSL pour les connexions sécurisées")
    parser.add_argument("--name", default="Serveur Pendu M1", help="Nom d'affichage du serveur pour la découverte réseau")
    parser.add_argument("--no-discovery", action="store_true", help="Désactiver l'annonce UDP Multicast")
    args = parser.parse_args()

    srv = Server(
        host=args.host,
        port=args.port,
        use_tls=args.tls,
        server_name=args.name,
        enable_discovery=not args.no_discovery,
    )
    try:
        asyncio.run(srv.start())
    except KeyboardInterrupt:
        print("\n[SERVEUR] Arrêt du serveur.")





