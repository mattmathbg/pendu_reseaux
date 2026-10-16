import asyncio
from protocol.framing import StreamFramer
from protocol.message import Message, ProtocolError

class Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 8888) -> None:
        self.host = host
        self.port = port

    #transforme un Message en octets, ajoute le \n, et l'envoie au client.
    async def send_message(self, writer: asyncio.StreamWriter, msg: Message) -> None:
        # serialize() : Message -> JSON en octets (L6 - Présentation)
        # frame() : ajoute le \n à la fin (L6 - Framing)
        writer.write(StreamFramer().frame(msg.serialize()))
        # attend que le buffer soit vidé avant de continuer
        await writer.drain()

    # RÉCEPTION : lit les octets du client, découpe les messages grâce au \n,
    # les désérialise, puis décide quoi répondre.
    async def recv(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        # un framer unique pour cette connexion client
        framer = StreamFramer()

        try:
            while True:
                # on lit un bloc d'octets sur la socket TCP (L4)
                chunk = await reader.read(4096)
                if not chunk:
                    break  # le client a fermé la connexion (EOF)

                # on donne les octets reçus au framer
                framer.feed(chunk)

                # on récupère tous les messages complets disponibles
                while True:
                    msg_bytes = framer.get_next_message()
                    if msg_bytes is None:
                        break  # plus de message complet, on retourne lire le réseau

                    try:
                        # octets -> objet Message (L6 - Présentation)
                        message_obj = Message.deserialize(msg_bytes)

                        # logique métier (L7) : pour l'instant, simple réponse "OK"
                        print(f"Reçu de {message_obj.type} avec id {message_obj.request_id}")

                        response = Message(
                            type="Type = " + message_obj.type,
                            request_id=message_obj.request_id,
                            session_id=message_obj.session_id,
                            payload={"status": "OK"}
                        )
                        await self.send_message(writer, response)

                    except ProtocolError as e:
                        # erreur de format/structure
                        err_response = Message(
                            type="ERROR",
                            request_id=0,
                            payload={"error": str(e)}
                        )
                        await self.send_message(writer, err_response)

        except ConnectionResetError:
            print("Connexion interrompue brutalement par le client.")
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def start(self):
        """Démarre le serveur TCP asynchrone."""
        # on passe 'self.recv' comme callback à asyncio.start_server
        server = await asyncio.start_server(self.recv, self.host, self.port)
        addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
        print(f"Serveur Pendu démarré sur {addrs}")
        async with server:
            await server.serve_forever()
if __name__ == "__main__":
    srv = Server(host="127.0.0.1", port=8888)
    asyncio.run(srv.start())