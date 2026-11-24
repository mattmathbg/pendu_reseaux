# Reste à faire — Pendu Réseau M1

Liste des actions et corrections restantes, classées par priorité, pour finaliser le projet avant la démonstration et le dépôt sur Arche.

> **Déjà réglé récemment :**
> - Bouton « Nouvelle manche » désactivé et grisé pendant une partie `EN_COURS` (`client/gui.py`).
> - `certs/server.key` retirée du suivi Git (`.gitignore`, `.dockerignore`, `docker-compose.yml`, CI/CD).
> - `get_word_from_api` non bloquant (`await asyncio.to_thread`) et vérification d'état avant appel API / `session.theme` (`server/server.py`).
> - Resynchronisation de l'IHM lors d'un `TIMEOUT` serveur (`server/server.py`, `client/gui.py`).
> - Rejet des mots vides/invalides et normalisation des ligatures `œ`/`æ` (`core/words.py`, `core/pendu.py`).
> - Tolérance aux anciens fichiers `session.json` dans `_read_sessions()` (`client/connection.py`).
> - Suppression du champ Port dans l'IHM (`client/gui.py`) et activation dual-stack par défaut dans Docker (`docker-compose.yml`, `Dockerfile`).
> - Rédaction de `COMPTE_RENDU.md` et mise à jour de `readme.md`.

---

## 1. Actions indispensables avant la soutenance / dépôt Arche

- [ ] **Vérifier les workflows GitHub Actions** (`CI Tests`, `Docker Build`, `Release Client`) suite au dernier push (`a43fe48`).
- [ ] **Tester Docker en dual-stack** : lancer `docker compose up --build` et vérifier que le serveur affiche bien `('0.0.0.0', 8888)` **et** `('::', 8888, 0, 0)`.
- [ ] **Régénérer la paire de certificats TLS** (`certs/server.crt` + `certs/server.key`) avec `openssl` (car l'ancienne clé privée existe encore dans l'historique Git avant le commit `a43fe48`), puis commit/push **uniquement** le nouveau `certs/server.crt`.
- [ ] **Répéter les 9 étapes de la démonstration** (page 7 de `Reseaux_MiniProjet.pdf`) : 2 clients simultanés, chat global/salon, coupure + clic sur « Reprendre », message invalide.
- [ ] **Préparer l'archive Arche** : code source complet + `COMPTE_RENDU.md` (+ `diagramme_machine_etats.svg` / `diagramme_uml_architecture.png`).

---

## 2. Bugs et améliorations techniques restants (par priorité)

### Priorité Élevée
- [ ] **Débloquer le thread principal Tkinter + sécuriser les logs (`client/gui.py`)**
  - Exécuter les appels réseau (`connect`, `resume`, `new_game`, `play`, `quit_game`, `chat`, `join_room`) dans un thread secondaire pour éviter que la fenêtre ne gèle pendant les timeouts TCP (5 s).
  - Passer les appels à `log_network_event` par `self._gui_queue` (Tkinter n'est pas thread-safe).
- [ ] **Fiabiliser l'idempotence et la reprise (`client/connection.py`, `core/session.py`)**
  - Sauvegarder `next_request_id` dans `session.json` pour éviter une collision avec `request_id = 1` après redémarrage + `RESUME`.
  - Élargir `last_response` côté serveur à un dictionnaire borné de requêtes récentes ou invalider l'ancien cache sur `RESUME`.
  - Décider entre rétablir le rejeu idempotent automatique (`retry_last` + `RESUME` dans un thread) ou supprimer les restes morts (`self.last_message` dans `GameClient.__init__`).
- [ ] **Corriger les cas limites de `resume_existing_session()` et `_check_saved_session()` (`client/gui.py`)**
  - Si `self.client.session_id` est déjà en mémoire mais que l'utilisateur change le champ `Pseudo` avant de cliquer sur « Reprendre », charger la session du nouveau pseudo au lieu de reprendre l'ancienne.
  - Filtrer les sessions expirées (`> 60 s`) dans `_check_saved_session()` pour ne pas activer « Reprendre » à tort au démarrage.
- [ ] **Éviter la fuite mémoire sur double `RESUME` (`server/server.py`)**
  - Dans `_dispatch_message` / `_handle_resume`, si la connexion TCP possède déjà une `current_session`, refuser `RESUME` (`INVALID_STATE`) ou appeler `current_session.handle_disconnect()` sur l'ancienne session avant de basculer.
- [ ] **Respecter le flag `use_tls` des serveurs découverts (`client/gui.py`)**
  - Ne plus forcer `self.client.use_tls = True` partout dans `gui.py` ; utiliser `s["use_tls"]` dans `_apply_server()` (et activer `self.tls_var`).
- [ ] **Assainir la découverte UDP (`protocol/discovery.py`)**
  - Remplacer/limiter le balayage unicast `/24` de 254 IP en boucle dans `discover_servers()`.
  - Joindre les groupes multicast sur toutes les interfaces réseau actives (pas seulement `INADDR_ANY` / index `0`) et remonter une alerte si le port UDP `8889` est déjà occupé.
- [ ] **Rendre `_push()` non-bloquant entre clients (`server/server.py`)**
  - Ne pas attendre `await writer.drain()` séquentiellement pour chaque destinataire dans `_handle_chat` et marquer déconnectée une session si `_push()` échoue avec `OSError`.

### Priorité Moyenne
- [ ] **Afficher le compte à rebours serveur `time_left` dans l'IHM (`client/gui.py`)**
  - Exploiter `payload["time_left"]` envoyé par le serveur dans `STATE` au lieu (ou en plus) du chronomètre local montant.
- [ ] **Restaurer `room_id` dans l'IHM après `RESUME` (`server/server.py`, `client/gui.py`)**
  - Inclure `"room_id": session.room_id` dans `_state_payload()` et mettre à jour `self._set_room(...)` dans `update_from_state()`.
- [ ] **Factoriser la gestion de déconnexion dans l'IHM (`client/gui.py`)**
  - Créer une méthode `_mark_disconnected()` appelée dans `_do()`, `_refresh()`, `connect_or_disconnect()` et `quit_game()` : ferme la socket, arrête le timer, désactive les touches, remet le bouton sur « Connexion » et désactive « Abandonner » hors session.
- [ ] **Restreindre le clavier physique à l'onglet « Jeu » (`client/gui.py`)**
  - Ajouter `if self.tabview.get() != "Jeu": return` au début de `_on_key_press()`.
- [ ] **Renforcer les contrôles protocole côté serveur (`server/server.py`, `protocol/message.py`)**
  - Vérifier `msg.session_id == current_session.session_id` sur les requêtes authentifiées dans `_dispatch_message`.
  - Refuser `request_id <= 0` pour les requêtes client dans `Message.deserialize` (`0` étant réservé aux pushs serveur).
- [ ] **Compter uniquement les joueurs connectés dans la découverte UDP (`server/server.py`)**
  - Dans `get_players_count`, compter les sessions avec `s.is_connected` au lieu de `len(self.sessions.sessions)`.

### Priorité Basse
- [ ] **Normaliser les accents dans `Pendu` et le clavier physique (`core/pendu.py`, `client/gui.py`)**
  - Retirer les accents dans `Pendu.__init__` et `_on_key_press` (AZERTY) et rejeter les caractères hors `[A-Z]` dans `Pendu.guess()`.
- [ ] **Améliorer l'inspecteur réseau (`client/connection.py`, `client/gui.py`)**
  - Logger les messages chat reçus en push dans `_store_if_push()`.
  - Passer `self.log_text` en `state="disabled"` (lecture seule).
- [ ] **Nettoyage de code**
  - Supprimer les imports inutilisés dans `server/server.py` (`from csv import writer`, `import random`, `from core import pendu`).
  - Supprimer la méthode morte `_target()` et corriger l'indentation de `_build_ui()` dans `client/gui.py`.
  - Supprimer le double appel `load_verify_locations` dans `create_client_ssl_context()` (`client/connection.py`).

---

## 3. Extensions optionnelles du sujet (si besoin de bonus)

- [ ] **Salles de jeu complètes (Extension B)** : implémenter `CREATE_ROOM` et `LIST_ROOMS`, et associer une partie/classement à chaque salle.
- [ ] **Mode Joueur contre Joueur (Extension A)** : deux joueurs dans la même salle jouent à tour de rôle ou en duel.
- [ ] **Certificat TLS avec SAN IP** : générer un certificat contenant les IP locales (Subject Alternative Name) afin de pouvoir réactiver `context.check_hostname = True` dans `client/connection.py`.
