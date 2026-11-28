import argparse
import asyncio
from csv import writer
import random
from time import time
from typing import Any
import uuid


from core import pendu
from core.pendu import (
    GameState,
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

from core.words import get_word_from_api

#---------------------------------------------------------------------
# SSL/TLS
#---------------------------------------------------------------------

import os
import ssl
from pathlib import Path

from server.duel import Duel, DuelError, FORFAIT_DELAY

def create_server_ssl_context(cert_dir: str = "certs") -> ssl.SSLContext:
    """Charge le certificat et la clé TLS utilisés pour accepter les clients."""
    path = Path(cert_dir)
    if not path.exists():
        root_alt = Path(__file__).resolve().parent.parent / cert_dir
        if root_alt.exists():
            path = root_alt
    cert_file = Path(os.environ.get("SSL_CERT_FILE") or (path / "server.crt"))
    key_file = Path(os.environ.get("SSL_KEY_FILE") or (path / "server.key"))
    if not cert_file.exists() or not key_file.exists():
        raise FileNotFoundError(
            f"Certificat ou clé TLS introuvable ({cert_file}, {key_file}). "
            "Générez une paire locale avec openssl ou définissez SSL_CERT_FILE / SSL_KEY_FILE."
        )
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(
        certfile=str(cert_file),
        keyfile=str(key_file),
    )
    return context

class Server:
    """Serveur réseau du pendu avec sessions, salons, parties et duels."""

    def __init__(
        self,
        host: str | list[str] | None = None,
        port: int = 8888,
        use_tls: bool = False,
        server_name: str = "Serveur Pendu M1",
        enable_discovery: bool = True,
        move_timeout: float = 60.0,
    ) -> None:
        """Configure les paramètres réseau, les sessions et les gestionnaires de messages."""
        # Par défaut, écoute sur toutes les interfaces réseau (Dual-Stack IPv4 et IPv6)
        if host is None:
            self.host = ["0.0.0.0", "::"]
        else:
            self.host = host
        self.port = port
        self.sessions = SessionManager(timeout=60)
        self.dispatcher = MessageDispatcher()
        self.duels: dict[str, Duel] = {}
        self.use_tls = use_tls  # Indique si le serveur doit utiliser TLS/SSL
        self.server_name = server_name
        self.enable_discovery = enable_discovery
        self.move_timeout = move_timeout

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
        self.dispatcher.register("CREATE_DUEL")(self._handle_create_duel)
        self.dispatcher.register("JOIN_DUEL")(self._handle_join_duel)

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
                duel = current_session.duel
                duel_state = f"{duel.duel_id} ({duel.status})" if duel else "aucun"
                print(
                    f"[SERVEUR] [SESSION] Session {current_session.session_id} "
                    f"joueur={current_session.player_name} duel={duel_state} "
                    "suspendue (en attente de RESUME sous 60s)."
                )
                if duel is not None and duel.status == "EN_COURS":
                    asyncio.create_task(
                        self._forfeit_after_disconnect(
                            duel, current_session, current_session.disconnect_timestamp
                        )
                    )
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
        """Crée une session pour un nouveau joueur et renvoie ses identifiants."""
        player_name = msg.payload.get("player_name", "Anonyme")
        session = self.sessions.create_session(player_name, move_timeout=self.move_timeout)
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
        """Vérifie les identifiants puis restaure une session suspendue."""
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


        # Reconnexion validée : on réinitialise le timer de coup et on renvoie l'état
        session.reset_move_timer()
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
        """Démarre une partie solo avec une catégorie optionnelle."""
        if session.game is not None and not session.game.is_finished():
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session.session_id,
                payload={"code": "INVALID_STATE", "message": "Une partie est déjà en cours."},
            )

        category_id = msg.payload.get("category_id")
        secret, theme = await asyncio.to_thread(get_word_from_api, category_id)
        session.theme = theme
        session.game = Pendu(secret_word=secret, max_errors=6)
        custom_timeout = msg.payload.get("timeout")
        if isinstance(custom_timeout, (int, float)) and not isinstance(custom_timeout, bool) and custom_timeout > 0:
            session.move_timeout = float(custom_timeout)
        session.reset_move_timer()
        return self._build_state_message(msg.request_id, session)

    async def _handle_letter(self, msg: Message, session: GameSession) -> Message:
        """Aiguillle une lettre vers le duel actif ou vers la partie solo."""
        if session.duel is not None:
            return await self._handle_duel_letter(msg, session)
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

        if session.is_timed_out():
            session.game.state = GameState.LOST
            payload = self._state_payload(session)
            payload["code"] = "TIMEOUT"
            payload["message"] = (
                f"Délai maximal de réflexion dépassé ({session.move_timeout}s). La partie est perdue."
            )
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session.session_id,
                payload=payload,
            )

        letter = msg.payload.get("letter", "")
        try:
            session.game.guess(letter)
            session.reset_move_timer()
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
        """Abandonne la partie en cours et supprime la session du joueur."""
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

    def _state_payload(self, session: GameSession) -> dict[str, Any]:
        """Construit le dictionnaire d'état courant d'une partie."""
        game = session.game
        payload: dict[str, Any] = {
            "masked_word": game.get_masked_word(),
            "errors_left": game.max_errors - game.current_errors,
            "used_letters": sorted(list(game.guessed_letters)),
            "status": game.state.value,
            "max_errors": game.max_errors,
            "time_left": round(session.time_left(), 1),
            "category": getattr(session, "theme", "DIVERS"),
        }
        if game.is_finished():
            payload["secret_word"] = game.secret_word
        return payload

    def _build_state_message(self, request_id: int, session: GameSession) -> Message:
        """Construit une réponse de type STATE contenant la projection complète de partie."""
        return Message(
            type="STATE",
            request_id=request_id,
            session_id=session.session_id,
            payload=self._state_payload(session),
        )

    async def _cleanup_loop(self) -> None:
        """Tâche de fond qui nettoie périodiquement les sessions expirées et vérifie les forfaits de duel."""
        while True:
            await asyncio.sleep(10)
            self.sessions.clean_expired_sessions()
            await self.check_duel_forfeits()

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
        """Valide le nom de salon puis associe le joueur à ce salon."""
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
        """Retire le joueur de son salon courant."""
        session.room_id = None
        return Message(
            type="ROOM",
            request_id=msg.request_id,
            session_id=session.session_id,
            payload={"room_id": None, "message": "Vous avez quitté le salon."},
        )


    async def _handle_chat(self, msg: Message, session: GameSession) -> Message:
        """Valide et distribue un message global ou à un salon."""
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
    
    async def _handle_create_duel(self, msg: Message, session: GameSession) -> Message:
        """Crée un duel en attente à partir du code demandé par le joueur."""
        if session.duel is not None:
            return self._duel_error("INVALID_STATE", "Vous êtes déjà dans un duel.", msg, session)
        requested_id = msg.payload.get("duel_id")
        if requested_id is None:
            duel_id = uuid.uuid4().hex[:8].upper()
        elif (
            not isinstance(requested_id, str)
            or not requested_id.isascii()
            or not requested_id.isalpha()
            or not 3 <= len(requested_id.strip()) <= 12
        ):
            return self._duel_error(
                "INVALID_DUEL_ID", "Le code doit contenir uniquement 3 à 12 lettres A-Z.", msg, session
            )
        else:
            duel_id = requested_id.strip().upper()
            if duel_id in self.duels:
                return self._duel_error("DUEL_EXISTS", "Ce code de duel est déjà utilisé.", msg, session)
        word, _theme = await asyncio.to_thread(get_word_from_api)
        duel = Duel(duel_id, creator=session, secret_word=word)
        self.duels[duel_id] = duel
        session.duel = duel
        return self._duel_message("DUEL", msg.request_id, session, duel)

    def _duel_message(self, msg_type: str, request_id: int, session: GameSession, duel: Duel) -> Message:
        """Construit une réponse réseau contenant l'état projeté du duel."""
        return Message(type=msg_type, request_id=request_id,
                       session_id=session.session_id, payload=duel.to_payload())

    def _duel_error(self, code: str, text: str, msg: Message, session: GameSession) -> Message:
        """Construit une erreur protocolaire liée à une action de duel."""
        return Message(type="ERROR", request_id=msg.request_id, session_id=session.session_id,
                       payload={"code": code, "message": text})

    async def _handle_join_duel(self, msg: Message, session: GameSession) -> Message:
        """Recherche un duel par code puis démarre la partie avec le second joueur."""
        if session.duel is not None:
            return self._duel_error("INVALID_STATE", "Vous êtes déjà dans un duel.", msg, session)
        requested_id = msg.payload.get("duel_id", "")
        duel_id = requested_id.strip().upper() if isinstance(requested_id, str) else ""
        duel = self.duels.get(duel_id)
        if duel is None:
            return self._duel_error("UNKNOWN_SESSION", "Duel inconnu.", msg, session)
        try:
            duel.add_player(session)
        except DuelError as exc:
            return self._duel_error(exc.code, exc.message, msg, session)
        session.duel = duel
        state_payload = duel.to_payload()
        for player in duel.players:
            if player is not session:
                await self._push(
                    player,
                    Message(type="DUEL_STATE", request_id=0, payload=state_payload),
                )
        return self._duel_message("DUEL", msg.request_id, session, duel)

    async def _handle_duel_letter(self, msg: Message, session: GameSession) -> Message:
        """Traite une proposition de lettre et informe les deux joueurs du résultat."""
        duel = session.duel
        try:
            duel.play(session, msg.payload.get("letter", ""))
        except DuelError as exc:
            return self._duel_error(exc.code, exc.message, msg, session)

        if duel.status == "TERMINE":
            end_payload = duel.to_payload()
            for other in duel.players:
                if other is not session:
                    await self._push(other, Message(type="DUEL_END", request_id=0, payload=end_payload))
            response = Message(type="DUEL_END", request_id=msg.request_id,
                               session_id=session.session_id, payload=end_payload)
            self._end_duel(duel)
            return response

        state_payload = duel.to_payload()
        for other in duel.players:
            if other is not session:
                await self._push(other, Message(type="DUEL_STATE", request_id=0, payload=state_payload))
        return self._duel_message("DUEL", msg.request_id, session, duel)

    async def check_duel_forfeits(self, now: float | None = None) -> None:
        """Parcourt les duels en cours et envoie DUEL_END à ceux qui ont gagné par forfait."""
        now = time() if now is None else now
        for duel in list(self.duels.values()):
            absent_players = [
                player for player in duel.players
                if not player.is_connected and player.disconnect_timestamp is not None
            ]
            for player in absent_players:
                absent_for = now - player.disconnect_timestamp
                print(
                    f"[DUEL] Contrôle forfait duel={duel.duel_id} statut={duel.status} "
                    f"joueur_absent={player.player_name} depuis={absent_for:.1f}s"
                )
            if duel.forfeit_if_absent(now):
                end = Message(type="DUEL_END", request_id=0, payload=duel.to_payload())
                for player in duel.players:
                    if player.owner is not None and player.is_connected:
                        await self._push(player, end)
                print(
                    f"[DUEL] Forfait déclaré duel={duel.duel_id} "
                    f"vainqueur={duel.winner or 'personne'}"
                )
                self._end_duel(duel)

    async def _forfeit_after_disconnect(
        self, duel: Duel, session: GameSession, disconnect_timestamp: float
    ) -> None:
        """Accorde le délai de reprise puis déclare un forfait si le joueur ne revient pas."""
        await asyncio.sleep(FORFAIT_DELAY)
        if (
            self.duels.get(duel.duel_id) is not duel
            or session.duel is not duel
            or session.is_connected
            or session.disconnect_timestamp != disconnect_timestamp
        ):
            return
        await self.check_duel_forfeits(now=time())

    def _end_duel(self, duel: Duel) -> None:
        """Détache les joueurs du duel terminé et retire celui-ci du registre."""
        for player in duel.players:
            player.duel = None
        self.duels.pop(duel.duel_id, None)


     
           


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serveur de Pendu Réseau")
    parser.add_argument("--host", default=None, help="Adresse d'écoute (défaut : dual-stack 127.0.0.1 et ::1)")
    parser.add_argument("--port", type=int, default=8888, help="Port d'écoute TCP (défaut : 8888)")
    parser.add_argument("--tls", action="store_true", default=True, help="Activer TLS/SSL pour les connexions sécurisées (défaut : activé)")
    parser.add_argument("--no-tls", dest="tls", action="store_false", help="Désactiver TLS/SSL")
    parser.add_argument("--name", default="Serveur Pendu M1", help="Nom d'affichage du serveur pour la découverte réseau")
    parser.add_argument("--no-discovery", action="store_true", help="Désactiver l'annonce UDP Multicast")
    parser.add_argument("--timeout", type=float, default=60.0, help="Durée maximale par coup en secondes (défaut : 60s)")
    args = parser.parse_args()

    srv = Server(
        host=args.host,
        port=args.port,
        use_tls=args.tls,
        server_name=args.name,
        enable_discovery=not args.no_discovery,
        move_timeout=args.timeout,
    )
    try:
        asyncio.run(srv.start())
    except KeyboardInterrupt:
        print("\n[SERVEUR] Arrêt du serveur.")





