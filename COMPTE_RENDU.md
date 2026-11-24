# Compte-rendu — Mini-projet Réseaux M1 : Jeu du Pendu en réseau

Ce document présente la conception, l'architecture, le protocole applicatif et les choix techniques du projet **Pendu Réseau**, réalisé en Python 3 au-dessus de TCP (avec découverte UDP et chiffrement TLS).

---

## 1. Architecture client–serveur et lien avec les couches réseau

Le projet suit une séparation stricte des responsabilités entre couche métier, couche protocole/transport, serveur et client :

```text
pendu_reseaux/
├── core/
│   ├── pendu.py          # Moteur de jeu pur (Pendu, GameState) — indépendant du réseau
│   ├── session.py        # Cycle de vie de session (GameSession, SessionManager, TTL, idempotence)
│   ├── words.py          # Récupération de mots (API trouve-mot.fr + normalisation + secours local)
│   └── exceptions.py     # Exceptions métier (InvalidStateError, InvalidLetterError, LetterAlreadyTriedError)
├── protocol/
│   ├── message.py        # Couche Présentation : Message JSON UTF-8, validation stricte, ProtocolError
│   ├── framing.py        # Délimitation de trames TCP par '\n' (StreamFramer, MAX_MESSAGE_SIZE = 8192)
│   └── discovery.py      # Découverte automatique LAN via UDP Multicast IPv4/IPv6 + Broadcast
├── server/
│   ├── server.py         # Serveur asyncio concurrent, TLS, dispatch, timeout, push chat
│   └── dispatcher.py     # Table de routage type de message -> handler asynchrone
└── client/
    ├── connection.py     # Client TCP/TLS, framing, persistance locale session.json, poll()
    ├── controller.py     # Contrôleur découplant l'interface graphique du transport réseau
    └── gui.py            # Interface graphique CustomTkinter (Jeu, Chat, Inspecteur réseau)
```

### Correspondance avec le modèle en couches

| Couche | Rôle dans le projet | Implémentation |
| :--- | :--- | :--- |
| **Transport** | Flux d'octets fiable point-à-point pour le jeu (TCP IPv4/IPv6) et datagrammes sans connexion pour la découverte (UDP). | `asyncio.start_server`, `socket.create_connection`, `socket.SOCK_DGRAM` |
| **Sécurité (sous-couche TLS)** | Chiffrement du canal TCP, intégrité des octets transportés et authentification du serveur par certificat X.509. | `ssl.SSLContext` (`certs/server.crt`, `certs/server.key`) |
| **Présentation & Framing** | Découpage du flux TCP en trames délimitées par `\n`, sérialisation/désérialisation JSON UTF-8 et contrôle strict des types. | `StreamFramer` ([protocol/framing.py](protocol/framing.py)), `Message` ([protocol/message.py](protocol/message.py)) |
| **Session** | Identification (`session_id`), authentification de reprise (`auth_token`), expiration par TTL (60 s), idempotence (`request_id`). | `GameSession`, `SessionManager` ([core/session.py](core/session.py)) |
| **Application** | Arbitrage des règles du Pendu, gestion des salons et diffusion des messages de chat. | `Pendu` ([core/pendu.py](core/pendu.py)), `Server` ([server/server.py](server/server.py)) |

---

## 2. Conception du protocole applicatif

### 2.1 Service rendu et principes fondamentaux

1. **Service rendu par le serveur :** le serveur arbitre des parties de Pendu indépendantes pour plusieurs clients concurrents : sélection du mot secret (avec catégorie), suivi des lettres essayées et des erreurs, gestion des sessions et reprises après coupure, application d'un délai maximal par coup (`move_timeout`), gestion de salons et relais de chat.
2. **Opérations demandées par le client :** `HELLO` (ouverture de session), `RESUME` (reprise après coupure), `NEW_GAME` (démarrage d'une manche, avec catégorie/timeout optionnels), `LETTER` (proposition d'une lettre), `JOIN_ROOM` / `LEAVE_ROOM` (salons), `CHAT` (envoi de message global ou de salon), `QUIT` (clôture propre).
3. **Réponses retournées par le serveur :** `WELCOME` (accueil avec `session_id` et `auth_token`), `STATE` (état courant ou final de la partie), `ROOM` (confirmation d'entrée/sortie de salon), `CHAT` (accusé de réception avec le `request_id` de l'émetteur, ou message poussé aux autres clients avec `request_id = 0`), `BYE` (confirmation de fermeture), `ERROR` (erreur applicative normalisée).
4. **Informations conservées par le serveur pendant une partie :** `session_id`, `auth_token`, `player_name`, `room_id`, `game` (`secret_word` en clair côté serveur uniquement, `guessed_letters`, `max_errors`, `current_errors`, `state`), `theme`, `is_connected`, `disconnect_timestamp`, `move_timeout`, `last_move_timestamp`, `owner` (flux TCP propriétaire courant) et `last_response` (cache d'idempotence).
5. **Autorité sur les règles :** **uniquement le serveur**. Le client n'a jamais accès au mot secret tant que la partie est `EN_COURS` ; il se contente d'envoyer une lettre et d'afficher l'état calculé par le serveur.
6. **Vérifications réalisées côté serveur :**
   * *Framing :* taille maximale d'une trame fixée à `8192` octets (`MAX_MESSAGE_SIZE`).
   * *Syntaxe & typage :* UTF-8 valide, objet JSON contenant `type` (`str`), `request_id` (`int` non booléen), `session_id` (`str | None`), `payload` (`dict`).
   * *Session & droits :* présence d'une session authentifiée pour toute commande hors `HELLO`/`RESUME`, vérification du `auth_token` en temps constant (`secrets.compare_digest`) lors d'un `RESUME`.
   * *Cohérence d'état :* refus d'un `NEW_GAME` si une partie est `EN_COURS`, refus d'un `LETTER` si aucune partie n'est lancée ou si elle est terminée, refus d'un deuxième `HELLO` sur la même connexion, refus d'un `CHAT` en portée `room` sans salon rejoint.
   * *Sémantique métier :* lettre alphabétique unique non encore proposée, vérification du délai `is_timed_out()`.

---

### 2.2 Format universel et catalogue complet des messages

Toutes les trames échangées sont des objets JSON UTF-8 encadrés par `\n` :

```json
{
  "type": "STRING",
  "request_id": 1,
  "session_id": "UUID_OU_NULL",
  "payload": {}
}
```

#### Messages Client → Serveur

| Type | Rôle | Champs `payload` obligatoires | Champs `payload` facultatifs | `session_id` requis ? | Réponse attendue | Erreurs possibles (`code`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `HELLO` | Ouvre une nouvelle session | — | `player_name` (`str`, défaut `"Anonyme"`) | Non (`null`) | `WELCOME` | `INVALID_MESSAGE`, `INVALID_STATE` (si session déjà active sur la connexion) |
| `RESUME` | Reprend une session existante après coupure TCP | `auth_token` (`str`) | — | **Oui** | `STATE` (état de la partie ou `status: "IDLE"`) | `INVALID_MESSAGE`, `UNKNOWN_SESSION`, `PLAYER_NOT_ALLOWED` |
| `NEW_GAME` | Démarre une nouvelle manche | — | `category_id` (`int`), `timeout` (`int \| float > 0`) | Oui (connexion authentifiée) | `STATE` (`status: "EN_COURS"`) | `UNKNOWN_SESSION`, `INVALID_STATE` (partie déjà en cours) |
| `LETTER` | Propose une lettre | `letter` (`str`, 1 lettre) | — | Oui | `STATE` (`EN_COURS`, `GAGNE` ou `PERDU`) | `UNKNOWN_SESSION`, `INVALID_STATE`, `INVALID_LETTER`, `TIMEOUT` |
| `JOIN_ROOM` | Rejoint un salon | `room` (`str`, 1 à 20 car.) | — | Oui | `ROOM` (`room_id`) | `UNKNOWN_SESSION`, `INVALID_MESSAGE` |
| `LEAVE_ROOM` | Quitte le salon courant | — | — | Oui | `ROOM` (`room_id: null`) | `UNKNOWN_SESSION` |
| `CHAT` | Envoie un message de chat | `text` (`str`, 1 à 200 car. après `.strip()`), `scope` (`"global" \| "room"`) | — | Oui | `CHAT` (avec le `request_id` de la requête) + push `CHAT` (`request_id: 0`) aux pairs | `UNKNOWN_SESSION`, `INVALID_MESSAGE`, `INVALID_STATE` (`scope="room"` sans salon) |
| `QUIT` | Clôture la session (abandonne la manche si `EN_COURS`) | — | — | Oui | `BYE` | `UNKNOWN_SESSION` |

#### Messages Serveur → Client

| Type | `request_id` | Contenu du `payload` | Rôle |
| :--- | :---: | :--- | :--- |
| `WELCOME` | `= requête` | `session_id`, `auth_token`, `player_name` | Confirme l'ouverture de session et délivre le jeton secret de reprise. |
| `STATE` | `= requête` | `masked_word`, `errors_left`, `used_letters`, `status`, `max_errors`, `time_left`, `category` (+ `secret_word` si partie terminée). Si aucune partie lancée après `RESUME` : `status: "IDLE"`, `message`. | Transmet l'état autoritaire complet de la partie. |
| `ROOM` | `= requête` | `room_id` (`str \| None`), `message` | Confirme le changement de salon. |
| `CHAT` | `= requête` (émetteur) ou `0` (push aux pairs) | `player`, `scope`, `room_id`, `text` | Accuse réception à l'émetteur (`request_id > 0`) ou pousse le message reçu aux autres clients (`request_id == 0`). |
| `BYE` | `= requête` | `message`, `status` (`"ABANDONNE"`, `"GAGNE"`, `"PERDU"` ou `null`) | Confirme la clôture définitive de la session côté serveur. |
| `ERROR` | `= requête` (ou `0` si erreur de framing/JSON) | `code`, `message` (et pour `TIMEOUT` : état final avec `status: "PERDU"`, `secret_word`, `masked_word`, etc.) | Signale une erreur applicative ou de protocole sans fermer la connexion (sauf trame invalide/trop longue). |

---

## 3. Flux TCP et Framing (`StreamFramer`)

TCP offre un **flux d'octets continu** (*byte stream*) et non un transport de messages discrets : deux `sendall()` successifs peuvent être lus en un seul `recv()` (messages collés), ou un seul message JSON peut être fragmenté sur plusieurs `recv()`.

### Mécanisme implémenté ([protocol/framing.py](protocol/framing.py))

1. **Mécanisme choisi :** encadrement par **délimiteur strict `\n` (`0x0A`)** avec taille maximale bornée à `MAX_MESSAGE_SIZE = 8192` octets. Comme la sérialisation JSON (`json.dumps`) échappe tout saut de ligne interne en `\\n`, l'octet `\n` ne peut apparaître qu'en fin de trame.
2. **Détection d'un message complet :** `StreamFramer.get_next_message()` recherche l'indice du premier `\n` dans son tampon `self.buffer` (`bytearray`). Tant que `\n` est absent, elle retourne `None` (tout en levant `ProtocolError("Message trop long")` si `len(self.buffer) > 8192` pour prévenir le déni de service mémoire).
3. **Traitement de plusieurs messages reçus dans un même `recv()` :** côté serveur (`server/server.py`) comme côté client (`GameClient.poll()`), la lecture extrait les trames dans une boucle `while True:` tant que `get_next_message()` ne renvoie pas `None`. Chaque appel supprime uniquement `[:delimiter_index + 1]` du buffer et laisse les messages suivants prêts pour l'itération suivante.
4. **Reconstitution d'un message reçu partiellement :** les octets reçus par `recv(4096)` sont ajoutés en fin de `self.buffer` via `framer.feed(chunk)`. Si aucun `\n` n'est encore présent, `get_next_message()` retourne `None` sans vider le buffer, et les fragments suivants viendront le compléter au `recv()` suivant.

---

## 4. Session applicative et machine à états

### Diagramme d'états d'une session et d'une partie

```text
                    [ DÉCONNECTÉ ]
                          │
                    HELLO (session créée)
                          ▼
               ┌──────► [ IDLE ] ◄──────────────────────────┐
               │       (game=None)                          │
               │          │                                 │
               │      NEW_GAME                              │
               │          ▼                                 │
               │     [ EN_COURS ] ◄──── RESUME (token OK) ──┤
               │       /   │   \                            │
   NEW_GAME    │  Victoire │  Défaite / TIMEOUT             │  Coupure TCP
   (nouvelle   │     │     │     │                          │  (handle_disconnect)
    manche)    │     ▼     │     ▼                          ▼
               ├─[ GAGNE ] │ [ PERDU ]             [ SUSPENDU (TTL 60s) ]
               │           │                                │
               │       QUIT (en cours)                      │ Expire (> 60s)
               │           ▼                                ▼
               └─────[ ABANDONNE ]                  [ SESSION SUPPRIMÉE ]
                           │
                     QUIT (session supprimée)
                           ▼
                    [ DÉCONNECTÉ ]
```

### Messages autorisés et refusés selon l'état

| État de la connexion / session | Messages autorisés | Messages refusés (et code renvoyé) |
| :--- | :--- | :--- |
| **Non authentifié** (`current_session is None`) | `HELLO`, `RESUME` | Tout autre message → `UNKNOWN_SESSION` ; `RESUME` invalide → `INVALID_MESSAGE` / `UNKNOWN_SESSION` / `PLAYER_NOT_ALLOWED` |
| **`IDLE`** (session ouverte, `game is None`) | `NEW_GAME`, `JOIN_ROOM`, `LEAVE_ROOM`, `CHAT`, `QUIT`, `RESUME` | `HELLO` → `INVALID_STATE` ; `LETTER` → `INVALID_STATE` |
| **`EN_COURS`** | `LETTER`, `JOIN_ROOM`, `LEAVE_ROOM`, `CHAT`, `QUIT`, `RESUME` | `HELLO` → `INVALID_STATE` ; `NEW_GAME` → `INVALID_STATE` |
| **`GAGNE` / `PERDU` / `ABANDONNE`** | `NEW_GAME`, `JOIN_ROOM`, `LEAVE_ROOM`, `CHAT`, `QUIT`, `RESUME` | `HELLO` → `INVALID_STATE` ; `LETTER` → `INVALID_STATE` |
| **`SUSPENDU`** (socket fermée, TTL ≤ 60 s) | `RESUME` (avec `session_id` + `auth_token` valides) | Toute commande sur une nouvelle socket non reprise → `UNKNOWN_SESSION` |
| **Expiré** (> 60 s déconnecté) ou après **`QUIT`** | `HELLO` (nouvelle session) | `RESUME` → `UNKNOWN_SESSION` |

---

## 5. Gestion des erreurs

### Erreur de transport vs Erreur applicative

| Critère | Erreur de transport | Erreur applicative |
| :--- | :--- | :--- |
| **Nature** | Rupture ou indisponibilité du canal TCP/TLS. | Le transport fonctionne, la trame est arrivée, mais la requête viole le protocole ou les règles du jeu. |
| **Exemples dans le projet** | `ConnectionError`, `ConnectionResetError`, `socket.timeout`, `OSError`, `ssl.SSLError`, `recv()` retournant `b""`. | Lettre invalide (`"12"`), lettre déjà essayée, `LETTER` sans partie, `RESUME` avec mauvais `auth_token`, dépassement de `move_timeout`. |
| **Traitement** | Le serveur suspend la session (`handle_disconnect`) et attend `RESUME` pendant 60 s ; le client ferme sa socket et affiche l'état déconnecté. | Le serveur renvoie un message JSON `ERROR` (`code` + `message`) et **maintient la connexion TCP ouverte** (sauf dépassement `MAX_MESSAGE_SIZE` ou JSON non décodable). |

### Catalogue des codes d'erreur implémentés

| Code | Déclencheur |
| :--- | :--- |
| `INVALID_MESSAGE` | JSON invalide, champ manquant ou mal typé, trame > 8192 octets, type d'action inconnu, `session_id` absent sur `RESUME`, nom de salon ou texte de chat invalide. |
| `INVALID_STATE` | `LETTER` sans partie ou sur partie terminée, `NEW_GAME` pendant une partie `EN_COURS`, deuxième `HELLO` sur connexion active, `CHAT` en mode `room` sans salon. |
| `INVALID_LETTER` | Proposition qui n'est pas une lettre alphabétique unique ou lettre déjà tentée (`InvalidLetterError`, `LetterAlreadyTriedError`). |
| `UNKNOWN_SESSION` | Commande métier sans session attachée, `RESUME` vers un `session_id` inexistant ou expiré (> 60 s). |
| `PLAYER_NOT_ALLOWED` | `RESUME` avec un `auth_token` invalide. |
| `TIMEOUT` | Dépassement de `move_timeout` (60 s par défaut) lors d'un `LETTER` : le serveur passe la partie à `PERDU` et renvoie le mot secret. |
| `INTERNAL_ERROR` | Exception inattendue dans un handler : aucune trace interne n'est divulguée au client et la connexion reste active. |

---

## 6. Serveur concurrent

Le serveur ([server/server.py](server/server.py)) repose sur **`asyncio.start_server`** :
* **Séparation socket d'écoute / sockets clients :** `asyncio.start_server(self.recv, self.host, self.port, ssl=ssl_context)` crée les sockets d'écoute (`0.0.0.0:8888` et `:::8888`). À chaque `accept()`, `asyncio` lance une coroutine `recv(reader, writer)` dédiée avec ses propres `StreamReader`, `StreamWriter`, `StreamFramer` et `current_session`.
* **Non-blocage de la boucle d'événements :** l'appel HTTP vers `trouve-mot.fr` dans `_handle_new_game` est délégué à un thread worker via `await asyncio.to_thread(get_word_from_api, category_id)` afin qu'une lenteur de l'API externe ne gèle jamais les autres joueurs.

---

## 7. Déconnexion, reprise de session et ambiguïté après coupure

### 7.1 Mécanisme de reprise (`RESUME`)
1. **Création des identifiants :** lors du `HELLO`, `GameSession` génère deux UUID4 aléatoires : `session_id` (identifiant public de session) et `auth_token` (jeton secret). Le client enregistre le couple par pseudo dans `session.json` (TTL 60 s).
2. **Délai de validité (TTL) :** lorsqu'une socket se ferme sans `QUIT`, `recv()` appelle `current_session.handle_disconnect()` qui enregistre `disconnect_timestamp`. La tâche de fond `_cleanup_loop()` purge les sessions déconnectées depuis plus de `60` secondes (`timeout = 60`).
3. **Preuve d'identité :** à la reconnexion, le client envoie `RESUME` avec `session_id` et `auth_token`. Le serveur vérifie le jeton en temps constant via `secrets.compare_digest(auth_token, self.auth_token)`.
4. **Gestion multi-socket :** si l'ancienne socket se ferme *après* qu'une nouvelle connexion a déjà repris la session, le bloc `finally` vérifie `if current_session.owner is writer:` avant d'appeler `handle_disconnect()`, évitant ainsi de suspendre la nouvelle connexion.
5. **Session expirée ou inconnue :** le serveur répond `ERROR` avec `code = "UNKNOWN_SESSION"`.

### 7.2 Ambiguïté après coupure et idempotence (`request_id`)
* **Problématique :** si la connexion coupe juste après l'envoi de `LETTER` (avant réception de `STATE`), le client ne sait pas si la lettre a été comptabilisée ou perdue.
* **Gestion côté serveur ([core/session.py](core/session.py), [server/server.py](server/server.py)) :**
  * Chaque requête métier validée est enregistrée via `session.save_response(msg.request_id, response)`.
  * Avant d'appeler le dispatcher, `_dispatch_message` consulte `current_session.get_cached_response(msg.request_id)`. En cas de retransmission du même `request_id`, le serveur **ne réexécute pas `Pendu.guess()`** et renvoie directement la réponse mise en cache.
* **Comportement côté client :** le client incrémente `next_request_id` à chaque nouvelle requête (`1, 2, ...`). En cas de coupure TCP pendant une requête, `GameClient.request()` lève `ConnectionError` vers l'IHM, qui ferme la socket et propose au joueur de cliquer sur **« Reprendre »** (`RESUME` avec les identifiants de `session.json`) pour retrouver l'état exact enregistré par le serveur sans perdre sa partie.

---

## 8. Extensions implémentées

### B — Salons (`JOIN_ROOM`, `LEAVE_ROOM`)
* Commandes `JOIN_ROOM` (nom de 1 à 20 caractères) et `LEAVE_ROOM` mettant à jour `session.room_id` et renvoyant `ROOM`.
* Permet d'isoler les discussions textuelles par salon (extension centrée sur les salons de chat ; le jeu reste individuel par session).

### C — Chat multiplexé en temps réel (`CHAT`)
* Deux portées supportées : `global` (tous les joueurs connectés) et `room` (uniquement les joueurs ayant le même `room_id`).
* **Multiplexage sur la même socket TCP :** pour éviter qu'un message chat poussé par le serveur ne soit confondu avec la réponse synchrone d'un `LETTER`, les pushs serveur portent `request_id = 0` tandis que les requêtes clients commencent à `1`. Côté client, `_read_message()` et `poll()` (appelé toutes les 200 ms par l'IHM) rangent les `request_id == 0` dans `self.inbox`.

### D — Chronomètre côté serveur (`move_timeout`)
* `GameSession` mesure le temps écoulé depuis le dernier coup (`last_move_timestamp`, défaut `60.0` s, configurable via `--timeout` ou `NEW_GAME`).
* À chaque `LETTER`, si `session.is_timed_out()` est vrai, le serveur déclare la partie perdue (`GameState.LOST`) et renvoie `ERROR` (`code = "TIMEOUT"`) enrichi de l'état final (`status = "PERDU"`, `secret_word`), permettant à l'IHM de stopper le jeu et de réactiver le bouton « Nouvelle manche ».

### F — Compatibilité Dual-Stack IPv4 / IPv6
* Par défaut (`host=None`), `Server` écoute simultanément sur `["0.0.0.0", "::"]` (port TCP `8888`).
* `test_ipv6_connection` valide explicitement l'échange `HELLO`/`WELCOME` sur `::1`, et `docker-compose.yml` configure un réseau bridge dual-stack (`172.28.0.0/16` et `fd00:dead:beef::/64`).

### G — Sécurité TLS
* **Implémentation :** serveur `asyncio` avec `ssl.Purpose.CLIENT_AUTH` (`certs/server.crt` et `certs/server.key`, configurables via `SSL_CERT_FILE` / `SSL_KEY_FILE`) ; client avec `ssl.Purpose.SERVER_AUTH` et épinglage de certificat (`CERT_REQUIRED`). La clé privée `certs/server.key` est exclue du suivi Git et de l'image Docker.
* **Ce que TLS apporte :**
  1. **Confidentialité :** chiffrement de bout en bout du flux TCP (empêche l'écoute du chat, des lettres et surtout du `auth_token`).
  2. **Intégrité transport :** empêche la modification silencieuse des trames en transit.
  3. **Authentification du serveur :** le client vérifie via le certificat épinglé qu'il parle au bon serveur.
* **Ce que TLS ne remplace pas dans le protocole applicatif :**
  1. **Le framing TCP :** TLS protège un flux d'octets, il ne découpe pas les messages applicatifs (`StreamFramer` reste indispensable).
  2. **La validation syntaxique et sémantique :** un client légitime connecté en TLS peut envoyer un JSON invalide, une lettre déjà jouée ou tricher sur les règles (contrôles `Message.deserialize` et `Pendu` indispensables).
  3. **L'authentification applicative et l'autorisation de session :** TLS authentifie le canal, pas le droit de reprendre une `GameSession` précise (`auth_token` + `secrets.compare_digest` restent nécessaires).
  4. **L'idempotence et la machine à états :** TLS ne gère pas la reprise applicative après coupure TCP (`RESUME` et `request_id`).

### Extensions supplémentaires
* **Découverte automatique UDP (`protocol/discovery.py`) :** service `DiscoveryServer` sur UDP `8889` (Multicast IPv4 `239.255.42.99`, Multicast IPv6 `ff02::42`, Broadcast) répondant aux sondes `DISCOVER` par une offre `OFFER` en Unicast.
* **Dictionnaire dynamique (`core/words.py`) :** 27 catégories via `trouve-mot.fr`, normalisation des ligatures (`œ`, `æ`) et accents, validation anti-mot vide et liste de secours `MOTS_SECOURS`.
* **Conteneurisation & CI/CD :** `Dockerfile`, `docker-compose.yml`, workflows GitHub Actions (tests `pytest` sous `xvfb`, image Docker multi-arch, binaire Windows `.exe`).
* **IHM CustomTkinter (`client/gui.py`) :** clavier A-Z interactif + clavier physique, bouton « Nouvelle manche » désactivé et grisé pendant une manche `EN_COURS`, onglet Chat filtré par portée et onglet Réseau affichant les trames en direct.

---

## 9. Principaux choix techniques, limites connues et démonstration

### Choix techniques clés
* **`asyncio` côté serveur vs threads :** évite le coût d'un thread par joueur et supprime les verrous partagés sur `SessionManager`, tout en isolant l'API HTTP synchrone dans `asyncio.to_thread`.
* **Délimiteur `\n` plutôt qu'en-tête binaire 4 octets :** lisible directement dans Wireshark et l'inspecteur réseau de l'IHM, tout en restant sans ambiguïté grâce à l'échappement JSON.
* **Découverte UDP + port fixe côté IHM :** l'utilisateur ne saisit que son pseudo et clique sur **« Découvrir »** (ou se connecte en local par défaut).

### Limites connues identifiées lors de l'audit
* `check_hostname = False` côté client pour supporter les certificats auto-signés sur IP LAN (compensé par l'épinglage du certificat `certs/server.crt`).
* Les appels TCP de l'IHM (hors découverte UDP) s'exécutent de manière synchrone sur le thread Tkinter ; en cas de coupure franche, l'UI peut figer jusqu'au timeout socket de 5 s.
* Le rejeu automatique (`retry_last`) a été retiré côté client ; le cache d'idempotence serveur ne mémorise que la dernière réponse (`last_response`).
* La découverte UDP réalise un balayage unicast `/24` de secours sur les interfaces détectées, et `_push()` diffuse les messages chat séquentiellement.

### Scénario de démonstration (9 attendus du sujet)
1. **Démarrage du serveur :** `python -m server.server` (ou `docker compose up --build`).
2. **Connexion d'un client :** `python -m client.gui`, clic sur **Découvrir** puis **Connexion** (`HELLO` → `WELCOME` visible dans l'onglet Réseau).
3. **Création d'une partie :** lancement automatique de `NEW_GAME` → `STATE` (`EN_COURS`), bouton **Nouvelle manche** grisé.
4. **Plusieurs échanges client ↔ serveur :** clics sur les touches `A–Z` (`LETTER` → `STATE`).
5. **Partie gagnée ou perdue :** fin de manche (`GAGNE` ou `PERDU` + mot révélé) → **Nouvelle manche** redevient cliquable.
6. **Traitement d'un message invalide :** vérifié par les tests automatisés (`test_malformed_message_returns_invalid_message`, `test_oversized_message_returns_error_and_closes_connection`, `test_invalid_letter_returns_invalid_letter`).
7. **Plusieurs clients simultanés :** lancer un second `python -m client.gui` avec un autre pseudo, jouer indépendamment et tester le chat global / par salon.
8. **Déconnexion d'un client :** fermer le client (ou couper la connexion) pendant une partie `EN_COURS` (le serveur suspend la session pour 60 s).
9. **Reconnexion et reprise de session :** relancer le client avec le même pseudo et cliquer sur **Reprendre** (`RESUME` → `STATE` avec progression intacte).

### Validation par tests automatisés
```powershell
pytest -v
```
Suite complète : **137 tests passés** (`core`, `protocol`, `server`, `client`, `gui`, intégration TCP/TLS/IPv6).
