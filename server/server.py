import asyncio
from protocol.framing import StreamFramer
from protocol.message import Message, ProtocolError

class Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 8888) -> None:
        self.host = host
        self.port = port

    def send_message(self, msg_dict: dict, framer: StreamFramer) -> bytes:
        # On crée l'objet Message à partir du dictionnaire
        msg_obj = Message(
            type=msg_dict["type"],
            request_id=msg_dict["request_id"],
            session_id=msg_dict.get("session_id"),
            payload=msg_dict.get("payload", {})
        )

        return framer.frame(msg_obj.serialize())  # Utilisation du framer pour le framing



    #La fonction recv est responsable de la réception des messages d'un client via un flux TCP. 
    # Elle utilise un StreamFramer pour gérer le découpage des messages et un Message pour la sérialisation/désérialisation.
    #async permet de définir une fonction asynchrone qui peut être suspendue et reprise
    async def recv(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        # on instancie un framer unique pour cette connexion client
        framer = StreamFramer()
        
        try:
            while True:
                # on lit un bloc d'octets sur le socket TCP (L4)
                chunk = await reader.read(4096)
                if not chunk:
                    break  # Le client a fermé la connexion (EOF)
                
                # on nourrit le framer avec le chunk reçu (L6 - Framing)
                framer.feed(chunk)
                
                # si il reste des messages dans le buffer, on récupère tous les messages complets disponibles
                while True:
                    others_msg_bytes = framer.get_next_message()
                    if others_msg_bytes is None:
                        break  # plus de message complet, on retourne lire le réseau
                    
                    try:
                        # on désérialise les octets en objet Message structuré (L6 - Présentation)
                        message_obj = Message.deserialize(others_msg_bytes)
                        
                        # on traite la logique métier selon le type de message (L7)
                        print(f"Reçu de {message_obj.type} avec id {message_obj.request_id}")
                        
                        # exemple de réponse :
                        response = Message(
                            type="Type = "+message_obj.type,
                            request_id=message_obj.request_id,
                            session_id=message_obj.session_id,
                            payload={"status": "OK"}
                        )
                        
                        # on encode et on envoie la réponse
                        writer.write(framer.frame(response.serialize()))
                        #attend que le buffer soit vidé avant de continuer
                        await writer.drain()
                        
                    except ProtocolError as e:
                        # Erreur de format/structure
                        err_response = Message(
                            type="ERROR",
                            request_id=0,
                            payload={"error": str(e)}
                        )
                        writer.write(framer.frame(err_response.serialize()))
                        await writer.drain()
                        
        except ConnectionResetError:
            print("Connexion interrompue brutalement par le client.")
        finally:
            writer.close()
            await writer.wait_closed()
     

    async def start(self):
            """Démarre le serveur TCP asynchrone."""
            # On passe 'self.recv' comme callback à asyncio.start_server
            server = await asyncio.start_server(self.recv, self.host, self.port)
            addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
            print(f"Serveur Pendu démarré sur {addrs}")
            async with server:
                await server.serve_forever()



if __name__ == "__main__":
    srv = Server(host="127.0.0.1", port=8888)
    asyncio.run(srv.start())