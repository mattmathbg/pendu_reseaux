from typing import Callable, Awaitable
from protocol.message import Message
from core.session import GameSession

# Signature attendue pour une action de jeu : (Message, GameSession) -> Message
HandlerFunc = Callable[[Message, GameSession], Awaitable[Message]]


class MessageDispatcher:
    """Associe chaque type de message à sa fonction de traitement serveur."""

    def __init__(self) -> None:
        """Initialise le registre des gestionnaires de messages."""
        self._handlers: dict[str, HandlerFunc] = {}

    def register(self, msg_type: str):
        """Décorateur ou méthode pour enregistrer un handler associé à un type de message."""
        def decorator(func: HandlerFunc) -> HandlerFunc:
            """Enregistre la fonction décorée et la retourne sans modification."""
            self._handlers[msg_type] = func
            return func
        return decorator

    async def dispatch(self, msg: Message, session: GameSession) -> Message:
        """Récupère le handler associé au type et l'exécute."""
        handler = self._handlers.get(msg.type)
        if handler is None:
            return Message(
                type="ERROR",
                request_id=msg.request_id,
                session_id=session.session_id,
                payload={
                    "code": "INVALID_MESSAGE",
                    "message": f"Action '{msg.type}' non reconnue."
                }
            )
        return await handler(msg, session)