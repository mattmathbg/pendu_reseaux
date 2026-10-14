import asyncio
import pytest
from server.server import Server  
from protocol.framing import StreamFramer
from protocol.message import Message

@pytest.mark.asyncio
async def test_server_recv_and_response():
    # 1. Instancier le serveur sur localhost et le port 0 (port aléatoire libre)
    server_instance = Server(host="127.0.0.1", port=0)
    
    # On démarre le serveur de la même manière que dans srv.start() mais programmatiquement
    server = await asyncio.start_server(
        server_instance.recv, server_instance.host, server_instance.port
    )
    
    # Récupérer l'adresse et le port attribués par l'OS
    addr = server.sockets[0].getsockname()
    host, port = addr[0], addr[1]

    async with server:
        # 2. Se connecter en tant que client de test
        reader, writer = await asyncio.open_connection(host, port)
        
        # 3. Créer un message valide
        msg = Message(
            type="NEW_GAME",
            request_id=42,
            payload={}
        )
        
        # 4. Envoyer le message au serveur (encadré par le framer)
        client_framer = StreamFramer()
        writer.write(client_framer.frame(msg.serialize()))
        await writer.drain()
        
        # 5. Lire la réponse du serveur
        response_chunk = await reader.read(1024)
        client_framer.feed(response_chunk)
        raw_response = client_framer.get_next_message()
        
        # Désérialiser la réponse
        response_msg = Message.deserialize(raw_response)
        
        # 6. Asserts (Vérifications)
        assert response_msg.request_id == 42
        assert response_msg.type == "Type = NEW_GAME"  
        assert response_msg.payload == {"status": "OK"}
        
        # 7. Fermeture propre du client
        writer.close()
        await writer.wait_closed()