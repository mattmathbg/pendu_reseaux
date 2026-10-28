from typing import Callable, Awaitable
from protocol.message import Message
from core.session import GameSession

# Signature attendue pour une action de jeu : (Message, GameSession) -> Message
HandlerFunc = Callable[[Message, GameSession], Awaitable[Message]]


class MessageDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, HandlerFunc] = {}

    def register(self, msg_type: str):
        """Décorateur ou méthode pour enregistrer un handler associé à un type de message."""
        def decorator(func: HandlerFunc) -> HandlerFunc:
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