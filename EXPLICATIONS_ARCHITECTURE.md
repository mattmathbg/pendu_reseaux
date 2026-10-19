# Guide Explicatif & Pédagogique — Architecture du Pendu Réseau M1

Ce document détaille le fonctionnement complet, pas-à-pas, de l'application client-serveur du Pendu. Il a été conçu pour vous permettre de **comprendre avec précision chaque octet échangé sur le réseau** et chaque choix d'architecture.

---

## 1. La Problématique Fondamentale : TCP et le Framing

### 1.1 Le Piège du "Flux Continu" (Stream-Oriented) de TCP
Contrairement à UDP qui transporte des **datagrammes** autonomes (avec des frontières nettes de paquets), TCP est un protocole de **flux d'octets continu** (*byte stream*). 
Pour TCP :
* Il n'y a **aucune notion de début ou de fin de message**.
* Si le client appelle `send("MESSAGE_A")` puis `send("MESSAGE_B")`, le serveur peut recevoir lors de son premier `recv()` :
  * Soit `MESSAGE_A` seul,
  * Soit `MESSAGE_AMESSAGE_B` (messages collés / concaténés),
  * Soit `MESS` (message tronqué / fragmenté), le reste arrivant au `recv()` suivant.

### 1.2 La Solution : Le `StreamFramer` avec Délimiteur `\n`
Pour redonner une frontière à nos messages applicatifs, nous utilisons la technique du **Framing par délimiteur** :
* Chaque message émis se termine obligatoirement par un saut de ligne UTF-8 : `\n` (octet `0x0A`).
* Le composant `StreamFramer` (`protocol/framing.py`) maintient un tampon d'octets (`bytearray`) :
  1. À chaque réception réseau, on ajoute les nouveaux octets avec `framer.feed(chunk)`.
  2. On recherche l'indice de `\n` dans le tampon :
     * S'il y est, on extrait tous les octets jusqu'au `\n` : c'est notre message complet ! On retire ces octets du tampon.
     * S'il n'y est pas, on attend le prochain `recv()`.

---

## 2. Structure et Catalogue des Messages (Couche Présentation)

Tout message échangé est un objet JSON encodé en UTF-8 :
```json
{
  "type": "STRING",
  "request_id": 1,
  "session_id": "STRING_OR_NULL",
  "payload": {}
}
```

* `type` : Nom de la commande ou de l'événement (`HELLO`, `WELCOME`, `NEW_GAME`, `LETTER`, `STATE`, `RESUME`, `QUIT`, `BYE`, `ERROR`).
* `request_id` : Entier séquentiel incrémenté à chaque nouvelle intention du client. Crucial pour **l'idempotence**.
* `session_id` : Identifiant unique de la session de jeu (UUID) généré par le serveur.
* `payload` : Dictionnaire contenant les paramètres spécifiques à l'action.

### Catalogue Standardisé :
| Type | Émetteur | Payload | Rôle |
| :--- | :--- | :--- | :--- |
| `HELLO` | Client | `{"player_name": str}` | Enregistre le joueur. Le serveur répond `WELCOME`. |
| `WELCOME` | Serveur | `{"session_id": str, "auth_token": str, "player_name": str}` | Confirme l'accueil et transmet les jetons de sécurité. |
| `NEW_GAME` | Client | `{}` | Lance une manche de pendu pour la session active. |
| `LETTER` | Client | `{"letter": str}` | Propose une lettre (ex. `"E"`). |
| `STATE` | Serveur | `{"masked_word": str, "errors_left": int, "used_letters": list, "status": str, ["secret_word": str]}` | État actualisé de la manche (`EN_COURS`, `GAGNE`, `PERDU`, `ABANDONNE`). |
| `RESUME` | Client | `{"auth_token": str}` | Demande de reprise de session après une coupure socket. |
| `QUIT` | Client | `{}` | Clôture propre de la session. Réponse : `BYE`. |
| `ERROR` | Serveur | `{"code": str, "message": str}` | Erreur (`BAD_REQUEST`, `UNAUTHORIZED`, `INVALID_MOVE`, `NO_GAME`). |

---

## 3. Cycle de Vie Complet d'un Paquet Réseau (Pas-à-Pas)

Voici exactement ce qui se passe quand le joueur clique sur une lettre, par exemple la lettre **'E'** dans l'interface graphique :

```
[ Joueur clique sur 'E' dans Tkinter GUI ]
                     │
                     ▼
  1. HangmanApp.play('E')
     appelle client.guess('E')
                     │
                     ▼
  2. GameClient.request('LETTER', {'letter': 'E'})
     - Numérote la requête : request_id = 3
     - Associe le session_id actif
     - Fabrique l'objet Message
                     │
                     ▼
  3. Framing & Sérialisation :
     raw_bytes = Message.serialize() + b'\n'
     Exemple : b'{"type":"LETTER","request_id":3,"session_id":"abc-123","payload":{"letter":"E"}}\n'
                     │
                     ▼
  4. Transmission TCP :
     sock.sendall(raw_bytes)  ─────────── [ Câble réseau / Boucle locale TCP ] ───────────►
                                                                                           │
                                                                                           ▼
                                                               5. Serveur asyncio.start_server
                                                                  reader.read(4096) reçoit les octets
                                                                                           │
                                                                                           ▼
                                                               6. StreamFramer.feed(chunk)
                                                                  Détection de b'\n' -> get_next_message()
                                                                                           │
                                                                                           ▼
                                                               7. Message.deserialize(raw)
                                                                  Vérification JSON & champs requis
                                                                                           │
                                                                                           ▼
                                                               8. Contrôles Serveur :
                                                                  - Session existante ? (Oui : abc-123)
                                                                  - Idempotence : request_id déjà vu ? (Non)
                                                                                           │
                                                                                           ▼
                                                               9. MessageDispatcher.dispatch() :
                                                                  Appelle _handle_letter()
                                                                                           │
                                                                                           ▼
                                                              10. Moteur Métier Pendu.guess('E') :
                                                                  - 'E' est-elle dans secret_word ?
                                                                  - Mise à jour de guessed_letters
                                                                  - Décompte des erreurs si absente
                                                                  - Vérification victoire / défaite
                                                                                           │
                                                                                           ▼
                                                              11. Construction du Message STATE :
                                                                  - masked_word : "_ E _ _ E"
                                                                  - errors_left : 5
                                                                  - used_letters : ["E"]
                                                                  - status : "EN_COURS"
                                                                                           │
                                                                                           ▼
                                                              12. Mise en cache d'idempotence :
                                                                  session.save_response(3, state_msg)
                                                                                           │
                                                                                           ▼
                                                              13. Encadrement & Envoi Réseau :
                                                                  writer.write(state_msg.serialize() + b'\n')
                                                                  await writer.drain()
                                                                                           │
                     ◄─────────── [ Câble réseau / Boucle locale TCP ] ────────────────────┘
                     │
                     ▼
 14. GameClient._read_message() :
     - Accumule les octets dans son StreamFramer
     - Dès le b'\n', désérialise le Message
     - Affiche la trame dans l'Inspecteur Réseau de la GUI
                     │
                     ▼
 15. HangmanApp.update_from_state() :
     - Met à jour le mot masqué : "_ E _ _ E"
     - Met à jour le dessin de la potence sur le Canvas
     - Désactive le bouton 'E' en vert (lettre correcte)
```

---

## 4. Résilience, Reconnexion (`RESUME`) et Idempotence

### 4.1 La Panne Réseau et le Timer de Session (TTL)
* Si le câble réseau est débranché ou si la socket est fermée, le serveur intercepte la fin de flux ou l'erreur `ConnectionResetError`.
* **Le serveur ne détruit pas la partie immédiatement !**
* Il marque la session comme déconnectée (`session.handle_disconnect()`) et mémorise l'horodatage.
* Une tâche de fond asynchrone (`_cleanup_loop`) accorde un **délai de grâce de 60 secondes (TTL)** pour permettre au joueur de se reconnecter.

### 4.2 La Reprise via `RESUME`
* Le client rouvre une socket TCP vers le serveur.
* Il envoie :
  ```json
  {
    "type": "RESUME",
    "request_id": 10,
    "session_id": "abc-123",
    "payload": { "auth_token": "secret-token-xyz" }
  }
  ```
* Le serveur compare le `auth_token`. Si le jeton est valide et la session non expirée, la session redevient active et le serveur renvoie l'état exact du jeu sans rien recommencer.

### 4.3 L'Idempotence par `request_id`
Imaginez le scénario critique suivant :
1. Le client envoie `LETTER 'Z'` avec `request_id = 4`.
2. Le serveur reçoit la lettre, constate que 'Z' est une erreur, retire une vie (5 -> 4), prépare la réponse...
3. **Coupure réseau pile au moment de l'envoi de la réponse !** Le client ne reçoit jamais la réponse.
4. Le client se reconnecte et réémet sa requête avec `retry_last()`.
* **Sans idempotence** : le serveur traiterait une 2e fois la lettre 'Z' et retirerait une 2e vie injustement !
* **Avec idempotence** : le serveur consulte son cache `last_response`. Comme `request_id == 4` a déjà été traité, il renvoie directement la réponse calculée précédemment **sans réexécuter `Pendu.guess()`**. Aucune pénalité en double !

### 4.4 Tester la Résilience en Direct
Dans l'interface graphique Tkinter :
1. Lancez une partie et jouez quelques lettres.
2. Cliquez sur le bouton orange **⚡ Simuler Coupure Réseau**.
3. La socket est fermée localement.
4. Cliquez ensuite sur une nouvelle lettre : observez dans la console de logs en bas de la fenêtre que le client détecte la coupure, se reconnecte à la volée, envoie `RESUME`, restaure sa session et joue votre lettre automatiquement !

---

## 5. Support Dual-Stack IPv4 / IPv6

Le serveur écoute simultanément sur les deux protocoles internet :
* **IPv4** : `127.0.0.1`
* **IPv6** : `::1`

Lors de l'initialisation, `asyncio.start_server(..., host=["127.0.0.1", "::1"], port=8888)` crée deux sockets d'écoute distinctes gérées par la même boucle d'événements.
Côté client, `socket.create_connection((host, port))` résout automatiquement l'adresse via `getaddrinfo`, permettant indifféremment une connexion en IPv4 ou en IPv6.

---

## 6. Guide de Démarrage Rapide

### 1. Lancer le Serveur
```powershell
python -m server.server
```
Options disponibles :
* `python -m server.server --port 9000` (changer le port)
* `python -m server.server --host 127.0.0.1` (forcer IPv4 uniquement)

### 2. Lancer l'Interface Graphique (GUI Tkinter)
Dans un autre terminal :
```powershell
python -m client.gui
```
* Entrez l'adresse (`127.0.0.1` ou `::1`) et votre pseudo.
* Jouez via les boutons de lettres.
* Observez les trames JSON défiler en temps réel dans l'Inspecteur Réseau.

### 3. Lancer l'Interface Ligne de Commande (CLI)
```powershell
python -m client.cli
```

### 4. Exécuter l'Ensemble des Tests Automatisés
```powershell
python -m pytest
```
* 59 tests unitaires et d'intégration validant le framing, les messages, le moteur métier, les sessions, l'idempotence, la reprise après déconnexion et l'IPv6.
