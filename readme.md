# 🎮 Pendu Réseau — Architecture Client-Serveur Asynchrone (M1 Informatique)

[![CI Tests](https://github.com/mattmathbg/pendu_reseaux/actions/workflows/ci.yml/badge.svg)](https://github.com/mattmathbg/pendu_reseaux/actions/workflows/ci.yml)
[![Docker Build](https://github.com/mattmathbg/pendu_reseaux/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/mattmathbg/pendu_reseaux/actions/workflows/docker-publish.yml)
[![Release Client](https://github.com/mattmathbg/pendu_reseaux/actions/workflows/release-client.yml/badge.svg)](https://github.com/mattmathbg/pendu_reseaux/actions/workflows/release-client.yml)
[![Python Version](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Dual-Stack](https://img.shields.io/badge/Réseau-IPv4%20%2F%20IPv6%20Dual--Stack-purple.svg)](#)
[![Security](https://img.shields.io/badge/Chiffrement-TLS%201.3-success.svg)](#)
[![License](https://img.shields.io/badge/Licence-MIT-green.svg)](#-auteur--licence)

Application complète de jeu du Pendu en réseau reposant sur une architecture client-serveur asynchrone hautement concurrente, tolérante aux pannes, chiffrée en TLS et conteneurisée.

---

## ⚡ Démarrage Rapide

### 1. Pour les Joueurs (Client Windows autonome)
Aucune installation de Python requise :
1. Rendez-vous dans la section [**Releases**](https://github.com/mattmathbg/pendu_reseaux/releases) du dépôt (publiée lors des tags `v*` ou via le workflow `Release Client`).
2. Téléchargez **`Pendu.exe`** (ou l'archive `Pendu-Windows-x64.zip`).
3. Double-cliquez pour lancer le jeu avec l'interface CustomTkinter !

> **Note TLS :** Le client embarque `certs/server.crt` pour vérifier l'identité du serveur en TLS. Si vous hébergez votre propre serveur, assurez-vous que le serveur utilise la paire de certificats correspondante (`certs/server.crt` + `certs/server.key`).

---

### 2. Pour les Administrateurs (Serveur Docker / GHCR)

L'image multi-architecture (`linux/amd64`, `linux/arm64`) est publiée sur **GitHub Container Registry** (`ghcr.io/mattmathbg/pendu_reseaux:latest`). Par sécurité, la clé privée TLS (`certs/server.key`) n'est **pas** incluse dans l'image.

#### Option A — Docker avec TLS activé (recommandé)
Montez votre dossier `certs/` contenant `server.crt` et `server.key` :

```bash
# Sur Linux / macOS
docker run -d \
  --name pendu_server \
  -p 8888:8888 \
  -p 8889:8889/udp \
  -v "$(pwd)/certs:/app/certs:ro" \
  --restart unless-stopped \
  ghcr.io/mattmathbg/pendu_reseaux:latest
```

Ou avec **Docker Compose** (depuis le dépôt cloné, avec réseau bridge Dual-Stack IPv4/IPv6 préconfiguré) :

```bash
docker compose up --build -d
```

#### Option B — Docker rapide sans certificat monté (`--no-tls` automatique)
Si aucune clé privée `/app/certs/server.key` (ni `SSL_KEY_FILE`) n'est fournie au conteneur, l'image bascule automatiquement sur `--no-tls` au démarrage :

```bash
docker run -d \
  --name pendu_server \
  -p 8888:8888 \
  -p 8889:8889/udp \
  --restart unless-stopped \
  ghcr.io/mattmathbg/pendu_reseaux:latest
```

---

### 3. Pour les Développeurs (Exécution depuis les sources)

#### Prérequis
```bash
python -m pip install -r requirements.txt
```

#### Générer une paire de certificats TLS locale (si `certs/server.key` est absent)
```bash
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout certs/server.key -out certs/server.crt \
  -days 365 -subj "/CN=localhost"
```

#### Démarrer le Serveur
Le chiffrement **TLS** et l'écoute **Dual-Stack (`0.0.0.0` et `::`)** sont activés par défaut :

```bash
# Serveur par défaut (port 8888, TLS activé, découverte UDP 8889, timeout 60 s)
python -m server.server

# Serveur TLS avec nom d'affichage et délai par coup personnalisés
python -m server.server --port 8888 --name "Serveur Pendu Master 1" --timeout 60

# Serveur sans chiffrement TLS (débogage local)
python -m server.server --no-tls
```

| Option | Défaut | Description |
| :--- | :--- | :--- |
| `--host` | `0.0.0.0` et `::` | Adresse(s) d'écoute TCP (Dual-Stack IPv4/IPv6 par défaut). |
| `--port` | `8888` | Port d'écoute TCP du serveur. |
| `--tls` / `--no-tls` | `--tls` (activé) | Active ou désactive le chiffrement TLS (`certs/server.crt` & `certs/server.key`, ou `SSL_CERT_FILE` / `SSL_KEY_FILE`). |
| `--name` | `"Serveur Pendu M1"` | Nom affiché lors de la découverte réseau UDP. |
| `--no-discovery` | `False` | Désactive l'annonce UDP Multicast / Broadcast (port `8889`). |
| `--timeout` | `60.0` | Délai maximal par coup en secondes. |

#### Démarrer le Client Graphique (IHM)
```bash
python -m client.gui
# ou via le point d'entrée :
python run_client.py
```

---

## 🌟 Points Forts & Fonctionnalités Clés

* **Architecture Asynchrone Haute Concurrence** : Serveur asynchrone bâti sur `asyncio.start_server` gérant de multiples sessions simultanées sans blocage (avec appels HTTP API déportés via `asyncio.to_thread`).
* **Framing Strict au-dessus de TCP** : Utilisation d'un encadrement de trames strict délimité par `\n` (`StreamFramer`, taille max `8192` octets) traitant la fragmentation, la concaténation de buffers et les coupures abruptes.
* **Tolérance aux Pannes & Idempotence** :
  * Reprise de session transparente (`RESUME` avec `session_id` + `auth_token` vérifié via `secrets.compare_digest`) après coupure réseau sans perte de progression (TTL `60 s`).
  * Détection d'idempotence basée sur `request_id` avec renvoi de la dernière réponse mise en cache sans recalcul côté serveur.
* **Dual-Stack & Résilience Réseau** : Prise en charge native d'IPv4 (`0.0.0.0`) et IPv6 (`::`), avec repli automatique sur `127.0.0.1` côté client en cas d'inaccessibilité de l'interface hôte.
* **Découverte Automatique UDP Multicast / Broadcast** :
  * Multicast IPv4 (`239.255.42.99`, RFC 2365) et Broadcast local sur le port UDP `8889`.
  * Multicast IPv6 Link-Local (`ff02::42`, RFC 4291).
  * Sondage instantané depuis l'interface client (bouton « Découvrir »).
* **Chiffrement TLS** : Sécurisation des flux applicatifs via `ssl.SSLContext` et certificats X.509 (`server.crt` / `server.key`) avec épinglage côté client.
* **Dictionnaire Dynamique & Secours Hors-ligne** :
  * Intégration de l'API `trouve-mot.fr` avec **27 catégories au choix** (Animaux, Voyages, Sports & Jeux, Arts, Aliments & Repas, etc.).
  * Nettoyage automatique des accents/ligatures (`œ`/`æ`) et repli immédiat sur `MOTS_SECOURS` en cas d'indisponibilité Internet.
* **Salons & Chat Multiplexé** : Salons de discussion (`JOIN_ROOM`, `LEAVE_ROOM`) et canal textuel en direct global ou par salon (`CHAT`, push serveur avec `request_id: 0`).
* **Interface Graphique Moderne (CustomTkinter)** : Thème sombre, clavier interactif + clavier physique, potence ASCII progressive, chronomètre et inspecteur de trames réseau en direct.

---

## 🏗️ Architecture & Spécification du Protocole

### Arborescence du Projet

```text
pendu_reseaux/
├── core/                  # Moteur Pendu, gestionnaire de sessions, dictionnaire API/secours
├── protocol/              # Messages JSON (Message), framing TCP (StreamFramer), découverte UDP
├── server/                # Serveur asyncio concurrent (Server) et routeur (MessageDispatcher)
├── client/                # Client TCP/TLS (GameClient), contrôleur et IHM CustomTkinter
├── certs/                 # Certificat public (server.crt) ; clé privée server.key hors Git
├── test/                  # Suite de 137 tests unitaires et d'intégration (pytest)
├── Dockerfile             # Image Docker serveur multi-arch
├── docker-compose.yml     # Stack Docker Dual-Stack IPv4/IPv6 + TLS
└── run_client.py          # Point d'entrée pour l'exécutable client Windows
```

### Diagramme de Classes (UML)

```text
┌───────────────────────────────────────────────────────────────┐
│                            Pendu                              │
├───────────────────────────────────────────────────────────────┤
│ - secret_word: str                                            │
│ - guessed_letters: set[str]                                   │
│ - max_errors: int                                             │
│ - current_errors: int                                         │
│ - state: GameState (EN_COURS, GAGNE, PERDU, ABANDONNE)        │
├───────────────────────────────────────────────────────────────┤
│ + guess(letter: str) -> bool                                  │
│ + get_masked_word() -> str                                    │
│ + is_finished() -> bool                                       │
│ + abandon() -> None                                           │
└───────────────────────────────▲───────────────────────────────┘
                                │ 1 compose
┌───────────────────────────────┴───────────────────────────────┐
│                       GameSession                             │
├───────────────────────────────────────────────────────────────┤
│ - session_id: str                                             │
│ - auth_token: str                                             │
│ - player_name: str                                            │
│ - room_id: str | None                                         │
│ - game: Pendu | None                                          │
│ - is_connected: bool                                          │
│ - move_timeout: float                                         │
│ - last_response: dict | None       // Cache d'idempotence     │
├───────────────────────────────────────────────────────────────┤
│ + handle_disconnect()                                         │
│ + reconnect(auth_token: str) -> bool                          │
│ + save_response(request_id: int, response: dict | Message)    │
│ + get_cached_response(request_id: int) -> dict | None         │
│ + is_timed_out() -> bool                                      │
└───────────────────────────────▲───────────────────────────────┘
                                │ * gère
┌───────────────────────────────┴───────────────────────────────┐
│                      SessionManager                           │
├───────────────────────────────────────────────────────────────┤
│ - sessions: dict[str, GameSession]                            │
│ - timeout: float                                              │
├───────────────────────────────────────────────────────────────┤
│ + create_session(player_name: str, move_timeout: float)       │
│ + get_session(session_id: str) -> GameSession | None          │
│ + clean_expired_sessions()                                    │
│ + remove_session(session_id: str) -> None                     │
└───────────────────────────────▲───────────────────────────────┘
                                │ utilise
┌───────────────────────────────┴───────────────────────────────┐
│                      MessageDispatcher                        │
├───────────────────────────────────────────────────────────────┤
│ - _handlers: dict[str, Callable]                              │
├───────────────────────────────────────────────────────────────┤
│ + register(msg_type: str)                                     │
│ + dispatch(msg: Message, session: GameSession)                │
└───────────────────────────────▲───────────────────────────────┘
                                │ traite
┌───────────────────────────────┴───────────────────────────────┐
│                       StreamFramer                            │
├───────────────────────────────────────────────────────────────┤
│ - buffer: bytearray                                           │
│ - delimiter: bytes (b"\n")                                    │
├───────────────────────────────────────────────────────────────┤
│ + feed(data: bytes)                                           │
│ + get_next_message() -> bytes | None                          │
│ + frame(data: bytes) -> bytes                                 │
└───────────────────────────────────────────────────────────────┘
```

---

### Format Universel des Messages

Chaque trame est sérialisée en JSON UTF-8 et encadrée par un saut de ligne strict `\n` :

```json
{
  "type": "STRING",
  "request_id": 1,
  "session_id": "UUID_STRING_OU_NULL",
  "payload": {}
}
```

### Catalogue des Types de Messages

| Type | Émetteur | Champs `payload` | Rôle & Réponse |
| :--- | :--- | :--- | :--- |
| `HELLO` | Client | `{"player_name": str}` (optionnel) | Ouverture de session. Réponse : `WELCOME` (`session_id`, `auth_token`, `player_name`). |
| `WELCOME` | Serveur | `{"session_id": str, "auth_token": str, "player_name": str}` | Confirmation de session et remise du jeton d'authentification. |
| `NEW_GAME` | Client | `{"category_id": int, "timeout": float}` (optionnels) | Démarre une manche (thème et délai par coup optionnels). Réponse : `STATE`. |
| `LETTER` | Client | `{"letter": str}` | Proposition d'une lettre. Réponse : `STATE` ou `ERROR`. |
| `STATE` | Serveur | `{"masked_word": str, "errors_left": int, "used_letters": list, "status": str, "max_errors": int, "time_left": float, "category": str}` | État actualisé de la partie (inclut `secret_word` en fin de manche, ou `status: "IDLE"` après `RESUME` sans partie). |
| `RESUME` | Client | `{"auth_token": str}` (`session_id` au niveau racine) | Restauration de session après coupure socket. Réponse : `STATE` ou `ERROR`. |
| `JOIN_ROOM` | Client | `{"room": str}` | Rejoint un salon (1 à 20 caractères). Réponse : `ROOM`. |
| `LEAVE_ROOM` | Client | `{}` | Quitte le salon courant. Réponse : `ROOM` (`room_id: null`). |
| `ROOM` | Serveur | `{"room_id": str \| null, "message": str}` | Confirmation de changement de salon. |
| `CHAT` | Client/Serveur | Client : `{"text": str, "scope": "room" \| "global"}` ; Serveur : inclut `player`, `room_id` | Message textuel diffusé aux pairs (`request_id: 0` en push). |
| `QUIT` | Client | `{}` | Clôture de session (abandonne la manche en cours). Réponse : `BYE`. |
| `BYE` | Serveur | `{"message": str, "status": str \| null}` | Confirmation de fermeture de session. |
| `ERROR` | Serveur | `{"code": str, "message": str}` | Erreur applicative (`INVALID_MESSAGE`, `INVALID_STATE`, `INVALID_LETTER`, `UNKNOWN_SESSION`, `PLAYER_NOT_ALLOWED`, `TIMEOUT`, `INTERNAL_ERROR`). |

---

### Machine à États Finis (FSM) de Session

```text
       [ DÉCONNECTÉ ]
              │
          recv(HELLO)
              ▼
           [ IDLE ] ◄──────────────────────────────────┐
              │                                        │
         recv(NEW_GAME)                                │
              ▼                                        │
          [ EN_COURS ]                                 │
        /     │      \                                 │
  Victoire  Défaite  QUIT / Coupure TCP                │
     │        │        │             │                 │
     ▼        ▼        ▼             ▼                 │
 [ GAGNE ] [ PERDU ] [ ABANDONNE ] [ SUSPENDU (60s) ]  │
     │        │        │             │                 │
     └────────┴────────┴── NEW_GAME ─┴── recv(RESUME) ─┘
```

---

## 🧪 Tests & Intégration Continue (CI / CD)

Le projet intègre **137 tests unitaires et d'intégration** validés automatiquement par **GitHub Actions** à chaque contribution :

```bash
# Exécution de la suite de tests avec pytest
pytest -v
```

### Pipelines Automatisés
- **CI Tests** (`.github/workflows/ci.yml`) : Exécution automatisée sous Linux Ubuntu avec serveur X virtuel (`xvfb`) pour les tests d'interface.
- **CD Docker Registry** (`.github/workflows/docker-publish.yml`) : Construction multi-architecture (`linux/amd64`, `linux/arm64`) et publication sur **GitHub Container Registry** (`ghcr.io`).
- **CD Windows Client** (`.github/workflows/release-client.yml`) : Compilation PyInstaller et publication de l'exécutable autonome `Pendu.exe` dans les GitHub Releases.

---

## 📚 Documentation Complémentaire

- 📖 [COMPTE_RENDU.md](COMPTE_RENDU.md) : Compte-rendu complet (architecture, spécification du protocole, framing, machine à états, gestion des erreurs, reprise de session, TLS, découverte UDP et choix techniques).
- 🧩 [diagramme_uml_architecture.png](diagramme_uml_architecture.png) : Diagramme UML de l'architecture.
- 🔄 [diagramme_machine_etats.svg](diagramme_machine_etats.svg) : Diagramme de la machine à états finis.

---

## 👥 Auteur & Licence

- Projet réalisé dans le cadre du **Master 1 Informatique — Module Réseaux**.
- Distribué sous licence **MIT**.
