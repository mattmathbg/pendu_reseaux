# 🎮 Pendu Réseau — Architecture Client-Serveur Asynchrone (M1 Informatique)

[![CI Tests](https://github.com/mattmathbg/pendu_reseaux/actions/workflows/ci.yml/badge.svg)](https://github.com/mattmathbg/pendu_reseaux/actions/workflows/ci.yml)
[![Docker Build](https://github.com/mattmathbg/pendu_reseaux/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/mattmathbg/pendu_reseaux/actions/workflows/docker-publish.yml)
[![Release Client](https://github.com/mattmathbg/pendu_reseaux/actions/workflows/release-client.yml/badge.svg)](https://github.com/mattmathbg/pendu_reseaux/actions/workflows/release-client.yml)
[![Python Version](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Dual-Stack](https://img.shields.io/badge/Réseau-IPv4%20%2F%20IPv6%20Dual--Stack-purple.svg)](#)
[![Security](https://img.shields.io/badge/Chiffrement-TLS%201.3-success.svg)](#)
[![License](https://img.shields.io/badge/Licence-MIT-green.svg)](LICENSE)

Application complète de jeu du Pendu en réseau reposant sur une architecture client-serveur asynchrone hautement concurrente, tolérante aux pannes, chiffrée en TLS et conteneurisée.

---

## ⚡ Démarrage Rapide

### 1. Pour les Joueurs (Client Windows autonome)
Aucune installation de Python requise :
1. Rendez-vous dans la section [**Releases**](https://github.com/mattmathbg/pendu_reseaux/releases) du dépôt.
2. Téléchargez **`Pendu.exe`** (ou l'archive `Pendu-Windows-x64.zip`).
3. Double-cliquez pour lancer le jeu avec l'interface CustomTkinter !

---

### 2. Pour les Administrateurs (Serveur Docker distant / VPS)
Déployez le serveur en une seule commande sur n'importe quel VPS (Linux x86/ARM) sans cloner le dépôt :

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

#### Démarrer le Serveur
```bash
# Serveur standard
python -m server.server

# Serveur sécurisé TLS avec nom d'affichage personnalisé
python -m server.server --tls --name "Serveur Pendu Master 1"
```

#### Démarrer le Client Graphique (IHM)
```bash
python -m client.gui
```

---

## 🌟 Points Forts & Fonctionnalités Clés

* **Architecture Asynchrone Haute Concurrence** : Serveur asynchrone bâti sur `asyncio.start_server` gérant de multiples sessions simultanées sans blocage.
* **Framing Strict au-dessus de TCP** : Utilisation d'un encadrement de trames strict délimité par `\n` (`StreamFramer`) traitant la fragmentation, la concaténation de buffers et les coupures abruptes.
* **Tolérance aux Pannes & Idempotence** :
  * Reprise de session transparente (`RESUME` avec `auth_token`) après coupure réseau sans perte de progression.
  * Détection d'idempotence basée sur `request_id` avec renvoi des réponses en cache sans recalcul côté serveur.
* **Dual-Stack & Résilience Réseau** : Prise en charge native d'IPv4 (`0.0.0.0`) et IPv6 (`::`), avec repli automatique sur `127.0.0.1` en cas d'inaccessibilité de l'interface hôte.
* **Découverte Automatique UDP Multicast / Broadcast** :
  * Multicast IPv4 (`239.255.42.99`, RFC 2365) et Broadcast local.
  * Multicast IPv6 Link-Local (`ff02::42`, RFC 4291).
  * Sondage instantané depuis l'interface client (bouton « 🔍 Découvrir »).
* **Chiffrement TLS 1.3** : Sécurisation intégrale des flux applicatifs via certificats X.509 (`server.crt` / `server.key`).
* **Dictionnaire Dynamique & Secours Hors-ligne** :
  * Intégration de l'API de mots avec **27 catégories au choix** (Animaux, Géographie, Cuisine, Sciences, Cinéma, etc.).
  * Nettoyage automatique des accents et repli immédiat sur liste locale en cas d'indisponibilité de l'accès Internet.
* **Salons Multi-Joueurs (Lobbies) & Chat Multiplexé** : Salons de jeu (`JOIN_ROOM`, `LEAVE_ROOM`) et canal de discussion textuelle en direct (`CHAT`).
* **Interface Graphique Moderne (CustomTkinter)** : Thème sombre, clavier interactif, potence vectorielle animée, chronomètre et inspecteur de trames réseau en direct.

---

## 🏗️ Architecture & Spécification du Protocole

### Diagramme de Classes (UML)

```text
┌───────────────────────────────────────────────────────────────┐
│                        HangmanGame                            │
├───────────────────────────────────────────────────────────────┤
│ - secret_word: str                                            │
│ - guessed_letters: set[str]                                   │
│ - max_errors: int                                             │
│ - current_errors: int                                         │
│ - state: GameState (IN_PROGRESS, WON, LOST, ABANDONED)        │
├───────────────────────────────────────────────────────────────┤
│ + guess(letter: str) -> bool                                  │
│ + get_masked_word() -> str                                    │
│ + is_finished() -> bool                                       │
└───────────────────────────────▲───────────────────────────────┘
                                │ 1 compose
┌───────────────────────────────┴───────────────────────────────┐
│                       GameSession                             │
├───────────────────────────────────────────────────────────────┤
│ - session_id: str                                             │
│ - auth_token: str                                             │
│ - player_name: str                                            │
│ - game: HangmanGame                                           │
│ - is_connected: bool                                          │
│ - move_timeout: float                                         │
│ - last_responses: dict[int, dict]  // Cache d'idempotence     │
├───────────────────────────────────────────────────────────────┤
│ + handle_disconnect(ttl_seconds: int)                         │
│ + reconnect(auth_token: str) -> bool                          │
│ + save_response(request_id: int, response: dict)              │
│ + get_cached_response(request_id: int) -> dict | None         │
│ + is_timed_out() -> bool                                      │
└───────────────────────────────▲───────────────────────────────┘
                                │ * gère
┌───────────────────────────────┴───────────────────────────────┐
│                      SessionManager                           │
├───────────────────────────────────────────────────────────────┤
│ - sessions: dict[str, GameSession]                            │
│ - timeout_task: asyncio.Task                                  │
├───────────────────────────────────────────────────────────────┤
│ + create_session(player_name: str) -> GameSession             │
│ + get_session(session_id: str) -> GameSession | None          │
│ + clean_expired_sessions()                                    │
└───────────────────────────────▲───────────────────────────────┘
                                │ utilise
┌───────────────────────────────┴───────────────────────────────┐
│                      MessageDispatcher                        │
├───────────────────────────────────────────────────────────────┤
│ - handlers: dict[str, Callable]                               │
├───────────────────────────────────────────────────────────────┤
│ + register(msg_type: str, handler: Callable)                  │
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
| `HELLO` | Client | `{"player_name": str}` | Authentification initiale. Réponse : `WELCOME` (`session_id`, `auth_token`). |
| `NEW_GAME` | Client | `{"category_id": int | null}` | Démarre une manche (avec thème optionnel). Réponse : `STATE`. |
| `LETTER` | Client | `{"letter": str}` | Proposition d'une lettre. Réponse : `STATE` ou `ERROR`. |
| `STATE` | Serveur | `{"masked_word": str, "errors_left": int, ...}` | Diffusion de l'état actualisé de la partie. |
| `RESUME` | Client | `{"auth_token": str}` | Restauration de session après coupure socket. Réponse : `STATE` ou `ERROR`. |
| `JOIN_ROOM` | Client | `{"room_id": str}` | Rejoint un salon multi-joueurs. Réponse : `ROOM_JOINED`. |
| `LEAVE_ROOM` | Client | `{}` | Quitte le salon courant. Réponse : `ROOM_LEFT`. |
| `CHAT` | Client/Serveur | `{"text": str, "scope": "room"\|"global"}` | Message textuel instantané diffusé aux pairs. |
| `QUIT` | Client | `{}` | Abandon ou fin ordonnée de session. Réponse : `BYE`. |
| `ERROR` | Serveur | `{"code": str, "message": str}` | Erreur applicative (`INVALID_LETTER`, `TIMEOUT`, `UNKNOWN_SESSION`). |

---

### Machine à États Finis (FSM) de Session

```text
       [ DÉCONNECTÉ ]
              │
          recv(HELLO)
              ▼
           [ IDLE ] ◄────────────────────────┐
              │                              │
         recv(NEW_GAME)                       │
              ▼                              │
          [ EN_COURS ]                       │
              │                              │
       ┌───────┼──────────────────┐           │
       │       │                  │           │
  recv(LETTER) │             Coupure TCP      │
       │       │                  │           │
       ▼       │                  ▼           │
   [ EVAL ]    │        [ DISCONNECTED_WAIT ] │
       │       │                  │           │
   ├───┴───────┤              recv(RESUME)    │
   │           │                  │           │
Victoire   Défaite               └───────────┤
   │           │                              │
   ▼           ▼                              │
 [ GAGNÉ ]  [ PERDU ]                         │
   │           │                              │
   └───────────┴─── Nouvelle partie ──────────┘
```

---

## 🧪 Tests & Intégration Continue (CI / CD)

Le projet intègre une suite de tests unitaires et d'intégration validée automatiquement par **GitHub Actions** à chaque contribution :

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

- 📖 [EXPLICATIONS_ARCHITECTURE.md](EXPLICATIONS_ARCHITECTURE.md) : Analyse détaillée du paquet réseau, du framing et des mécanismes de résilience.
- 📡 [EXPLICATIONS_DECOUVERTE_SERVEUR.md](EXPLICATIONS_DECOUVERTE_SERVEUR.md) : Fonctionnement du protocole de découverte UDP Multicast / Broadcast.
- 📐 [DESIGN.md](DESIGN.md) : Conception logicielle, choix de design et séparation des responsabilités.
- 📜 [Conception_du_protocole_applicatif.md](Conception_du_protocole_applicatif.md) : Spécification formelle initiale du protocole applicatif.

---

## 👥 Auteur & Licence

- Projet réalisé dans le cadre du **Master 1 Informatique — Module Réseaux**.
- Distribué sous licence **MIT**.
