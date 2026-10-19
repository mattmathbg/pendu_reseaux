
# Spécification & Feuille de Route — Mini-Projet Réseaux M1 (Pendu Réseau)



## 1. Objectifs & Exigences Fondamentales

* Développer une application client-serveur de jeu du Pendu au-dessus de TCP.


* **Serveur autoritaire** : le serveur valide les règles, maintient l'état et calcule la victoire/défaite.


* **Framing strict** : isoler les messages applicatifs du flux d'octets continu de TCP.


* **Concurrence & Résilience** : gérer plusieurs clients en simultané, les déconnexions inopinées et la reprise de session avec idempotence.



---

## 2. Diagramme de Classes & Architecture (UML)

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
│ - disconnect_timestamp: float | None                          │
│ - last_responses: dict[int, dict]  // Cache d'idempotence     │
├───────────────────────────────────────────────────────────────┤
│ + handle_disconnect(ttl_seconds: int)                         │
│ + reconnect(auth_token: str) -> bool                          │
│ + save_response(request_id: int, response: dict)              │
│ + get_cached_response(request_id: int) -> dict | None         │
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
│ + dispatch(msg: ProtocolMessage, session: GameSession)        │
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

## 3. Spécification Formelle du Protocole

### 3.1 Mécanisme de Framing



* **Délimiteur** : Saut de ligne UTF-8 `\n` (`0x0A`).


* Chaque trame sérialisée se termine obligatoirement par `\n`.


* Le récepteur accumule les fragments dans un tampon `bytearray` et n'extrait un message que lorsqu'un `\n` apparaît.



### 3.2 Structure Universelle de Message



Tout message échangé est un objet JSON encodé en UTF-8 :

```json
{
  "type": "STRING",
  "request_id": 1,
  "session_id": "STRING_OR_NULL",
  "payload": {}
}

```

### 3.3 Catalogue des Messages



| Type | Émetteur | Champs `payload` | Rôle & Réponse attendue |
| --- | --- | --- | --- |
| `HELLO`<br> | Client | `{"player_name": str}` | Enregistre le joueur. Réponse : `WELCOME` avec `session_id` et `auth_token`.

 |
| `NEW_GAME`<br> | Client | `{}` | Lance une manche. Réponse : `STATE`.

 |
| `LETTER`<br> | Client | `{"letter": str}` | Propose une lettre. Réponse : `STATE` ou `ERROR`.

 |
| `STATE`<br> | Serveur | `{"masked_word": str, "errors_left": int, "used_letters": list, "status": str}`<br> | État mis à jour de la partie courante.

 |
| `RESUME`<br> | Client | `{"auth_token": str}`<br> | Reprise de session après coupure socket. Réponse : `STATE` ou `ERROR`.

 |
| `ERROR`<br> | Serveur | `{"code": str, "message": str}`<br> | Erreur applicative (`INVALID_STATE`, `UNKNOWN_SESSION`, `BAD_REQUEST`).

 |

---

## 4. Machine à États Finis (FSM) de Session



```text
       [ DECONNECTÉ ]
              │
         recv(HELLO)
              ▼
           [ IDLE ] ◄────────────────────────┐
              │                              │
        recv(NEW_GAME)                       │
              ▼                              │
         [ EN_COURS ]                        │
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

## 5. Journal des Tâches — Feuille de Route d'Implémentation

### Phase 1 : Le Moteur Métier (0 % réseau)
* [x] Écrire `core/pendu.py` : logique pure du Pendu (mot masqué, vies décomptées, ensemble de lettres).
* [x] Créer un script de test local vérifiant le comportement sans aucune socket (`test/test_pendu.py`).

### Phase 2 : Le Protocole & Le Framing
* [x] Écrire `protocol/framing.py` : classe `StreamFramer` avec méthode `feed()` et buffer d'accumulation.
* [x] Tester les 3 pièges de flux TCP : message fragmenté, messages collés dans un seul buffer, flux vide (`test/test_framing.py`).
* [x] Écrire `protocol/message.py` : sérialisation/désérialisation JSON et contrôle des types (`test/test_message.py`).

### Phase 3 : Sessions, Résilience & Idempotence
* [x] Écrire `core/session.py` : gestionnaire associant `session_id`, `auth_token` et cache `{request_id: last_response}`.
* [x] Implémenter le timer de déconnexion (expiration automatique de la session après 60 s) et le nettoyage asynchrone.
* [x] Tests unitaires complets sur la gestion des sessions et de l'idempotence (`test/test_session.py`).

### Phase 4 : Serveur Concurrent, Clients (GUI/CLI) & Reconnexion
* [x] Mettre en place `server/server.py` avec `asyncio` pour traiter plusieurs connexions en simultané.
* [x] Développer `client/connection.py` : gestion de socket, retry transparent, idempotence, sauvegarde de session.
* [x] Développer `client/gui.py` : interface graphique Tkinter avec dessin dynamique du Pendu, statut réseau et inspecteur de trames.
* [x] Développer `client/cli.py` : interface en ligne de commande avec art ASCII du pendu et support de reprise.
* [x] Tester le scénario de déconnexion brutale et reprise via `RESUME` (`test/test_integration.py`).

### Phase 5 : Extensions Prioritaires (Objectif 20/20)
* [x] **Dual-Stack IPv4 / IPv6** : socket serveur configurée pour accepter `127.0.0.1` et `::1` simultanément.
* [ ] **Chiffrement TLS** : sécuriser la socket avec `ssl.create_default_context()`.
* [ ] **Salons & Mode 1v1 (PvP)** : gestion de lobbies via `ROOM_CREATE` et `ROOM_JOIN`.
* [ ] **Chat multiplexé** : échange de messages textuels dans la session sans bloquer le jeu.

> 📖 **Consulter le guide détaillé :** Voir [EXPLICATIONS_ARCHITECTURE.md](file:///c:/Users/mmath/Documents/M1/Reseaux/pendu_reseaux/EXPLICATIONS_ARCHITECTURE.md) pour l'explication pas-à-pas du paquet réseau, du framing et de la résilience.