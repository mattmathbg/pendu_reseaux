from dataclasses import asdict, dataclass, field
import json

class ProtocolError(Exception):
    """Erreur levée lors de la réception d'un message invalide."""
    pass

@dataclass
class Message:
     
    
     type: str
     request_id: int
     session_id: str | None = None
     payload: dict = field(default_factory=dict)
    
     def serialize(self) -> bytes:
          """
          Convertit l'objet Message en chaîne JSON UTF-8 (bytes)
          """
          return json.dumps(asdict(self)).encode("utf-8")

     @classmethod
     def deserialize(cls, data: bytes) -> "Message":
          """
          Convertit une chaîne JSON UTF-8 (bytes) en objet Message
          """
          try:
               raw = data.decode("utf-8")
               parsed = json.loads(raw)
          except (UnicodeDecodeError, json.JSONDecodeError) as e:
               raise ProtocolError("Format du message invalide") from e
          
          if not isinstance(parsed, dict):
               raise ProtocolError("Le message doit être un objet JSON")
          
          if "type" not in parsed or "request_id" not in parsed:
               raise ProtocolError("Le message doit contenir 'type' et 'request_id'")

          if not isinstance(parsed["type"], str):
               raise ProtocolError("Le champ 'type' doit être une chaîne de caractères")

          if not isinstance(parsed["request_id"], int) or isinstance(parsed["request_id"], bool):
               raise ProtocolError("Le champ 'request_id' doit être un entier")

          if parsed.get("session_id") is not None and not isinstance(parsed.get("session_id"), str):
               raise ProtocolError("Le champ 'session_id' doit être une chaîne de caractères ou None")

          if not isinstance(parsed.get("payload"), dict) and "payload" in parsed:
               raise ProtocolError("Le champ 'payload' doit être un dictionnaire ")
          
          return cls(
               type=parsed["type"],
               request_id=parsed["request_id"],
               session_id=parsed.get("session_id"),
               payload=parsed.get("payload", {}),
          )
     