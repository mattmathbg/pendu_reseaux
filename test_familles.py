import sys
from client.connection import GameClient
from client.controller import GameController

adresse = sys.argv[1]          # "127.0.0.1" pour IPv4, "::1" pour IPv6
client = GameClient()
controleur = GameController(client)

reponse = controleur.connect([{"host": adresse}], 8888, "Test")
print("Réponse du serveur :", reponse.type)
print("Famille de la socket :", client.sock.family.name)
client.close()