# Guide Complet — Découverte Automatique de Serveurs (UDP Multicast & Broadcast)

Ce document explique en détail le fonctionnement du système de **découverte automatique de serveurs** (Service Discovery) implémenté dans le projet Pendu Réseau M1. Il est conçu pour vous donner une maîtrise totale de l'architecture, du code et des concepts réseaux, ainsi que les réponses à toutes les questions qu'un enseignant ou jury pourrait vous poser.

---

## 1. Problématique & Objectif : Le "Zero-Conf"

### 1.1 Le problème initial
Dans une architecture client-serveur classique, un client a besoin de deux informations pour établir une connexion TCP :
* L'**adresse IP** du serveur (ex. `192.168.1.42`)
* Le **port d'écoute** (ex. `8888`)

Dans une salle de TP ou sur un réseau local domestique, cela oblige chaque joueur à exécuter `ipconfig` ou `ip a`, chercher son adresse IP locale, puis la communiquer oralement aux autres joueurs pour qu'ils la saisissent manuellement dans l'interface graphique.

### 1.2 La solution : Découverte "Zero-Configuration"
En intégrant un protocole de découverte automatique de service (similaire dans l'esprit à **mDNS / Bonjour** ou **SSDP**) :
1. Le joueur lance le serveur : le serveur annonce sa présence en tâche de fond sur le réseau local.
2. Le joueur lance le client et clique sur **« 🔍 Découvrir »**.
3. En moins d'une seconde, tous les serveurs du réseau local sont détectés et listés avec leur nom, leur adresse, leur port, le chiffrement TLS et le nombre de joueurs en cours.
4. L'utilisateur clique sur le serveur souhaité : les champs sont pré-remplis instantanément.

---

## 2. Architecture Réseau & Flux d'Échange

Le projet combine intelligemment **deux protocoles de transport** :
* **UDP (User Datagram Protocol) :** Utilisé pour la phase de découverte (sans connexion, supporte la diffusion 1-vers-N).
* **TCP (Transmission Control Protocol) :** Utilisé pour la phase de jeu (orienté connexion, ordonné, garanti et sécurisable par TLS).

### 2.1 Diagramme de Séquence Réseau

```
┌──────────────┐                                            ┌──────────────┐
│ CLIENT (GUI) │                                            │   SERVEUR    │
└──────┬───────┘                                            └──────┬───────┘
       │                                                           │
       │  [ Clic sur "🔍 Découvrir" ]                              │
       │                                                           │
       │  1. Sonde UDP Multicast IPv4 (239.255.42.99:8889)         │
       │ ─────────────────────────────────────────────────────────>│ (Écoute UDP
       │  2. Sonde UDP Broadcast IPv4 (255.255.255.255:8889)       │  DiscoveryServer)
       │ ─────────────────────────────────────────────────────────>│
       │  3. Sonde UDP Multicast IPv6 (ff02::42:8889)              │
       │ ─────────────────────────────────────────────────────────>│
       │     Payload: {"type": "DISCOVER"}                         │
       │                                                           │
       │                                              [ Analyse du paquet ]
       │                                              [ Prépare OFFER ]
       │                                                           │
       │  4. Réponse UDP UNICAST vers l'IP:Port du Client          │
       │ <─────────────────────────────────────────────────────────│
       │     Payload: {"type": "OFFER", "server_name": "Pendu M1", │
       │               "tcp_port": 8888, "players_count": 1, ...}  │
       │                                                           │
       │  [ Déduplication + Extraction IP réelle via recvfrom ]    │
       │  [ Remplissage auto du formulaire ou fenêtre modale ]     │
       │                                                           │
       │  5. Établissement de la Connexion de Jeu TCP (8888)       │
       │ ═════════════════════════════════════════════════════════>│
       │     Protocole Applicatif (HELLO -> WELCOME -> JEU...)     │
```

---

## 3. Détail des Choix Réseaux (Adresses, Ports & Scopes)

### 3.1 Pourquoi du Multicast plutôt que du simple Broadcast ?
* **Broadcast (`255.255.255.255`) :** Envoie le paquet à **tous** les équipements du domaine de diffusion (ordinateurs, imprimantes, box, télévisions connectées). La carte réseau de chaque machine doit interrompre son processeur pour inspecter le paquet, même si la machine ne s'intéresse pas du tout au Pendu. De plus, de nombreux switchs ou routeurs WiFi modernes filtrent ou limitent le broadcast.
* **Multicast IPv4 (`239.255.42.99`) :** N'arrose que les machines dont les applications se sont explicitement inscrites au groupe Multicast (`IP_ADD_MEMBERSHIP`). Les cartes réseau des autres machines filtrent le paquet au niveau matériel (adresse MAC multicast) sans solliciter l'OS.
  * **RFC 2365 :** L'adresse `239.255.42.99` appartient à la plage `239.0.0.0/8` réservée pour le *Multicast Administratif Privé*. Elle est garantie de ne jamais sortir sur l'Internet public.
* **Multicast IPv6 (`ff02::42`) :** 
  * En IPv6, le Broadcast n'existe plus (il a été aboli).
  * L'adresse commence par `ff02::`, ce qui signifie **Portée Link-Local** (RFC 4291). Le paquet est strictement cantonné au câble physique ou au SSID WiFi local.

### 3.2 Double Sécurité : Le Broadcast de secours
Certains commutateurs réseau bon marché ou mal configurés ne supportent pas le protocole **IGMP Snooping** et bloquent les flux Multicast. Pour parer à cette éventualité, notre fonction `discover_servers()` émet la sonde en Multicast **ET** envoie un paquet de secours en Broadcast IPv4.

---

## 4. Format des Messages Échangés

Les datagrammes UDP transportent du JSON encodé en UTF-8 :

### A. La Requête Client (`DISCOVER`)
```json
{
  "type": "DISCOVER"
}
```

### B. La Réponse Serveur (`OFFER`)
```json
{
  "type": "OFFER",
  "server_name": "Serveur Pendu M1",
  "tcp_port": 8888,
  "players_count": 2,
  "use_tls": false
}
```

> **Astuce Réseau Fondamentale :** Remarquez que le serveur n'indique **pas** sa propre adresse IP dans le JSON. C'est un choix d'ingénierie volontaire : si le serveur indiquait son IP, il risquerait d'indiquer une mauvaise interface (ex: `127.0.0.1`, une interface virtuelle VirtualBox ou Docker).
> 
> Le client récupère l'adresse IP réelle de l'émetteur directement depuis l'en-tête IP du paquet reçu grâce au tuple retourné par l'appel système :
> ```python
> data, addr = sock.recvfrom(2048)
> ip_reelle = addr[0]  # Exemple: '192.168.1.35'
> ```

---

## 5. Anatomie du Code Source

### 5.1 Côté Serveur : `DiscoveryServer` (`protocol/discovery.py`)
Le serveur de découverte s'exécute dans un thread d'arrière-plan (`daemon=True`) pour ne pas bloquer la boucle d'événements principale `asyncio` du serveur de jeu :

1. **Création des Sockets d'écoute :**
   * Deux sockets UDP sont ouverts : un pour IPv4 (`AF_INET`), un pour IPv6 (`AF_INET6`).
   * Option `SO_REUSEADDR` : Permet à plusieurs processus ou tests unitaires d'écouter sur le même port UDP (`8889`).
   * Inscription Multicast :
     * En IPv4 via `struct.pack("4sL", inet_aton("239.255.42.99"), INADDR_ANY)` avec `IP_ADD_MEMBERSHIP`.
     * En IPv6 via `inet_pton(AF_INET6, "ff02::42")` avec `IPV6_JOIN_GROUP`.
2. **Boucle d'écoute non-bloquante (`select.select`) :**
   * Surveille les sockets avec un timeout de 0.5s.
   * Dès qu'un paquet arrive, il est décodé. Si `type == "DISCOVER"`, le serveur interroge en temps réel le gestionnaire de sessions (`len(sessions)`) et répond immédiatement en **Unicast** à l'expéditeur :
     ```python
     sock.sendto(raw_offer, sender_addr)
     ```
   * *Pourquoi Unicast pour la réponse ?* Parce que seul le client demandeur a besoin de l'information. Répondre en Multicast inonderait inutilement le réseau.

### 5.2 Côté Client : `discover_servers()` (`protocol/discovery.py`)
1. **Création des Sockets émettrices :**
   * `IP_MULTICAST_TTL = 1` : Limite la portée du paquet à 1 saut (*hop*), interdisant tout routage en dehors du sous-réseau local.
   * `IP_MULTICAST_LOOP = 1` : Active la boucle locale (*loopback*). Cela permet au client de détecter un serveur qui tourne sur le même ordinateur (essentiel pour les tests et le développement).
2. **Collecte & Déduplication :**
   * Le client écoute pendant `1.2` seconde avec `select.select()`.
   * Plusieurs paquets peuvent arriver pour le même serveur (ex. reçu via Multicast ET via Broadcast, ou sur plusieurs interfaces).
   * Les serveurs sont mémorisés dans un dictionnaire avec pour clé `clean_ip:tcp_port`. Les doublons sont ainsi éliminés naturellement.

### 5.3 Côté Interface Graphique : `client/gui.py`
* **Exécution Asynchrone :** L'appel réseau `discover_servers()` dure 1.2 seconde. S'il était exécuté dans le thread principal de Tkinter/CustomTkinter, **la fenêtre gèlerait complètement** pendant plus d'une seconde.
* Nous utilisons donc [`_run_async()`](file:///C:/Users/mmath/Documents/M1/S7/Reseaux/pendu_reseaux/client/gui.py#L1225) qui délègue la recherche à un thread séparé et réinjecte le résultat dans le thread graphique via `root.after()`.
* **Expérience utilisateur :**
  * Si **0 serveur** trouvé : message d'information invitant à vérifier que le serveur est démarré.
  * Si **1 serveur** trouvé : remplissage automatique des champs Hôte, Port et coche TLS, puis notification de succès.
  * Si **plusieurs serveurs** trouvés : ouverture d'une boîte de dialogue modale permettant au joueur de choisir son serveur en un clic.

---

## 6. Docker & Conteneurisation

### 6.1 Configuration des Ports
Dans le [`Dockerfile`](file:///C:/Users/mmath/Documents/M1/S7/Reseaux/pendu_reseaux/Dockerfile) et [`docker-compose.yml`](file:///C:/Users/mmath/Documents/M1/S7/Reseaux/pendu_reseaux/docker-compose.yml), deux ports sont exposés :
* `8888/tcp` : Flux de jeu applicatif (TCP).
* `8889/udp` : Flux de découverte réseau (UDP).

### 6.2 Écoute `0.0.0.0` vs `127.0.0.1`
Dans un conteneur Docker, une écoute sur `127.0.0.1` n'écoute que sur la boucle locale *interne* au conteneur, rendant le serveur inaccessible depuis la machine hôte.
Le `Dockerfile` et `docker-compose.yml` démarrent donc explicitement le serveur avec `--host 0.0.0.0`, ce qui lie l'écoute sur l'interface virtuelle `eth0` du conteneur.

---

## 7. Preshot des Questions Pièges du Professeur

Voici les questions techniques pointues qu'un enseignant de Réseaux en Master 1 ou école d'ingénieurs est susceptible de vous poser, ainsi que la réponse idéale :

---

### Q1. « Pourquoi avoir utilisé UDP pour la découverte alors que tout le reste de votre jeu est en TCP ? »
> **Réponse attendue :**
> « TCP est un protocole point-à-point, orienté connexion : il nécessite une négociation en trois temps (*3-way handshake* SYN, SYN-ACK, ACK) qui suppose de connaître déjà l'adresse IP de destination. On ne peut pas faire de connexion TCP vers "tout le monde".
> UDP, au contraire, est un protocole sans connexion (*connectionless*) basé sur des datagrammes indépendants. C'est le seul protocole de niveau 4 capable de faire du Multicast et du Broadcast. C'est pour cela que tous les protocoles de découverte (mDNS, SSDP, DHCP) utilisent UDP. Une fois l'IP et le port découverts via UDP, nous basculons sur TCP pour garantir la fiabilité du jeu. »

---

### Q2. « Pourquoi la sonde client est envoyée en Multicast, mais la réponse du serveur se fait en Unicast ? »
> **Réponse attendue :**
> « Le client ne sait pas où sont les serveurs, il doit donc interroger l'ensemble du réseau : la sonde est nécessairement Multicast. 
> En revanche, quand le serveur reçoit la sonde via `recvfrom()`, la couche socket lui fournit l'adresse IP et le port source éphémère du client (`sender_addr`). Le serveur sait donc exactement qui a posé la question. Répondre en Multicast ou Broadcast inonderait le réseau pour rien ; le serveur répond donc en Unicast direct à l'adresse de l'expéditeur pour économiser la bande passante. »

---

### Q3. « Comment le client connaît l'adresse IP du serveur si le serveur ne la met pas dans son message JSON ? »
> **Réponse attendue :**
> « Le serveur ne renvoie que son port TCP (`tcp_port`). L'adresse IP est récupérée par le client directement au niveau de la couche réseau (IP) via le tuple `(ip, port)` que retourne l'appel système `sock.recvfrom(2048)`. 
> C'est d'ailleurs bien plus robuste : si le serveur a plusieurs cartes réseau (WiFi, Ethernet, Docker, VPN), une IP écrite en dur dans le payload pourrait être inaccessible pour le client. En lisant l'adresse source du paquet IP reçu, on a la certitude d'utiliser l'adresse par laquelle la communication passe réellement. »

---

### Q4. « Pourquoi positionner le TTL Multicast à 1 (`IP_MULTICAST_TTL = 1`) ? »
> **Réponse attendue :**
> « Le TTL (Time-To-Live) en IPv4, ou *Hops Limit* en IPv6, décrémente de 1 à chaque franchissement de routeur. En le fixant à 1, nous garantissons mathématiquement que les paquets de découverte ne franchiront aucun routeur et ne quitteront jamais le réseau local. Cela évite toute pollution réseau et empêche que des sondes privées ne soient routées vers l'extérieur. »

---

### Q5. « À quoi sert l'option de socket `SO_REUSEADDR` dans votre DiscoveryServer ? »
> **Réponse attendue :**
> « En UDP Multicast, plusieurs processus situés sur la même machine peuvent souhaiter écouter le même port (8889) pour recevoir les messages d'un groupe. Sans `SO_REUSEADDR`, le premier socket qui fait un `bind()` bloque tous les autres avec une erreur `EADDRINUSE`. Cette option permet le partage du port entre plusieurs récepteurs et est essentielle pour nos tests automatisés et les environnements multi-instances. »

---

### Q6. « Pourquoi avoir mis `IP_MULTICAST_LOOP = 1` côté client ? »
> **Réponse attendue :**
> « Par défaut sur certains systèmes d'exploitation, les paquets Multicast émis par une machine ne lui sont pas renvoyés en boucle locale. En activant `IP_MULTICAST_LOOP`, on autorise la pile réseau de l'OS à délivrer le paquet Multicast aux processus locaux qui ont rejoint le groupe. Cela permet à un client et un serveur tournant sur le même PC de se découvrir sans problème. »

---

### Q7. « Si plusieurs serveurs répondent, comment évitez-vous les collisions ou les blocages ? »
> **Réponse attendue :**
> « Comme nous sommes en UDP, chaque réponse est un datagramme indépendant placé dans le buffer de réception du socket du client. Côté client, nous utilisons `select.select()` avec une fenêtre temporelle de 1.2s :
> 1. Chaque datagramme est lu l'un après l'autre via `recvfrom()`.
> 2. Nous stockons les réponses dans un dictionnaire indexé par `IP:PORT` pour dédupliquer les offres (au cas où un serveur répondrait à la fois en Multicast et en Broadcast).
> 3. Si plusieurs serveurs différents répondent, l'IHM ouvre une modale de sélection listant tous les serveurs avec leurs métadonnées pour laisser le joueur choisir. »

---

### Q8. « Que se passe-t-il si un paquet corrompu ou un attaquant envoie n'importe quoi sur le port UDP 8889 ? »
> **Réponse attendue :**
> « Notre implémentation est défensive et protégée contre les erreurs de parsing (fuzzing) :
> * Le répondeur vérifie le décodage UTF-8 et le parsing JSON dans un bloc `try...except (UnicodeDecodeError, json.JSONDecodeError)`.
> * Il vérifie que le message est bien un dictionnaire contenant `"type": "DISCOVER"`.
> * Tout paquet malformé est silencieusement ignoré sans planter le thread ni fermer le socket. Nous avons d'ailleurs un test unitaire dédié dans `test/test_discovery.py` (`test_discovery_ignores_invalid_packet`) qui valide cette robustesse. »

---

### Q9. « Comment assurez-vous que la recherche ne bloque pas l'interface graphique ? »
> **Réponse attendue :**
> « La méthode `discover_servers()` attend 1.2s pour laisser le temps aux réponses réseau d'arriver. Si nous appelions cette méthode directement dans le thread de la boucle événementielle Tkinter (`mainloop`), l'application ne répondrait plus pendant 1.2s (effet "fenêtre blanche / ne répond pas").
> Nous utilisons donc une fonction asynchrone dédiée `_run_async` : la recherche est exécutée dans un `threading.Thread` d'arrière-plan, et dès que les résultats sont disponibles, nous utilisons `self.root.after(0, callback)` pour mettre à jour les éléments graphiques en toute sécurité sur le thread principal de Tkinter. »

---

## 8. Synthèse des Commandes Utiles pour l'Examen

| Action | Commande |
| :--- | :--- |
| **Lancer le serveur standard (avec découverte)** | `python -m server.server` |
| **Lancer le serveur sans découverte** | `python -m server.server --no-discovery` |
| **Lancer le serveur avec un nom personnalisé** | `python -m server.server --name "Serveur Salle TP 3"` |
| **Lancer le client graphique** | `python -m client.gui` |
| **Lancer le serveur dans Docker** | `docker compose up --build -d` |
| **Exécuter tous les tests (122 tests)** | `pytest` |
| **Exécuter uniquement les tests de découverte** | `pytest test/test_discovery.py -v` |
