class StreamFramer:
     def __init__(self, delimiter: bytes = b"\n") -> None:
        self.buffer = bytearray()
        self.delimiter = delimiter
     
     def feed(self, data):
          """rajoute la data au buffer

          Args:
              data (bytes): la data à rajouter
          """
          self.buffer.extend(data)
          
     def get_next_message(self) -> bytes | None:
          """
          Cherche le délimiteur dans le tampon.
          - Si trouvé : extrait le message, nettoie le tampon et retourne les octets du message.
          - Sinon : retourne None (message incomplet en attente de la suite)
          """
          delimiter_index = self.buffer.find(self.delimiter)
          if delimiter_index == -1:
               return None  # Pas encore de fin de message complète

          # On extrait tout ce qui se trouve avant le délimiteur
          message = bytes(self.buffer[:delimiter_index])

          # On retire le message ET le délimiteur du buffer
          del self.buffer[:delimiter_index + len(self.delimiter)]

          return message
     
     def frame(self, message: bytes) -> bytes:
          """
          Encadre le message avec le délimiteur pour l'envoi.
          """
          return message + self.delimiter
     