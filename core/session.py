
import time
import uuid

from core.pendu import Pendu
from protocol.message import Message


class GameSession:
     session_id: str
     auth_token: str
     player_name: str
     game: Pendu | None
     is_connected: bool
     disconnect_timestamp: float | None
     
     def __init__(self, player_name: str) -> None:
          self.session_id = str(uuid.uuid4())
          self.auth_token = str(uuid.uuid4())
          self.player_name = player_name
          self.game = None
          self.is_connected = True
          self.disconnect_timestamp = None
          self.owner = None
     
     def handle_disconnect(self) -> None:
          """
          Gère la déconnexion d'un joueur en mettant à jour l'état de la session.
          """
          self.is_connected = False
          self.disconnect_timestamp = time.time()
     
     def reconnect(self, auth_token: str) -> None:
          if auth_token != self.auth_token:
               return False
          self.is_connected = True
          self.disconnect_timestamp = None
          return True

     def save_response(self, request_id: int, response: dict | Message) -> None:
          self.last_response = {
               "request_id": request_id,
               "response": response.serialize() if isinstance(response, Message) else response
               }
          
     def get_cached_response(self, request_id: int) -> dict | None:
          if hasattr(self, "last_response") and self.last_response["request_id"] == request_id:
               return self.last_response["response"]
     
     def is_expired(self, timeout: float = 60) -> bool:
          """
          Vérifie si la session a expiré après un certain délai d'inactivité.
          """
          if self.is_connected:
               return False
          if self.disconnect_timestamp is None:
               return True
          return (time.time() - self.disconnect_timestamp) > timeout

class SessionManager:
     sessions: dict[str, GameSession]
     timeout: float     
     def __init__(self, timeout: float = 60) -> None:
          self.sessions = {}
          self.timeout = timeout
          
          
     def create_session(self, player_name: str) -> GameSession:
          session = GameSession(player_name)
          self.sessions[session.session_id] = session
          return session
     
     def get_session(self, session_id: str) -> GameSession | None:
          x = self.sessions.get(session_id)
          if x and x.is_expired(self.timeout):
               del self.sessions[session_id]
               return None
          return x
     
     def clean_expired_sessions(self) -> None:
          expired_sessions = [session_id for session_id, session in self.sessions.items() if session.is_expired(self.timeout)]
          for session_id in expired_sessions:
               del self.sessions[session_id]
     
     def remove_session(self, session_id: str) -> None:
          if session_id in self.sessions:
               del self.sessions[session_id]
          