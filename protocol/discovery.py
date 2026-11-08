"""
Module de découverte automatique de serveurs de jeu via UDP Multicast / Broadcast.

Ce module permet :
1. Aux serveurs de Pendu d'annoncer leur présence sur le réseau local via Multicast.
2. Aux clients de sonder le réseau local et d'obtenir en temps réel la liste des serveurs disponibles.

Architecture réseau :
- IPv4 Multicast : 239.255.42.99 (Groupe administratif privé local, RFC 2365)
- IPv4 Broadcast : <broadcast> / 255.255.255.255 (secours)
- IPv6 Multicast : ff02::42 (Portée Link-Local, RFC 4291)
- Port UDP par défaut : 8889
"""

import json
import logging
import select
import socket
import struct
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_DISCOVERY_PORT: int = 8889
MULTICAST_IPV4_GROUP: str = "239.255.42.99"
MULTICAST_IPV6_GROUP: str = "ff02::42"


class DiscoveryServer:
    """
    Service d'annonce UDP fonctionnant en tâche de fond sur le serveur.
    
    Écoute sur les groupes Multicast IPv4 et IPv6, et répond aux sondes 'DISCOVER'
    par un message 'OFFER' contenant les métadonnées de connexion TCP du serveur.
    """

    def __init__(
        self,
        tcp_port: int = 8888,
        server_name: str = "Serveur Pendu",
        discovery_port: int = DEFAULT_DISCOVERY_PORT,
        use_tls: bool = False,
        get_players_count: Callable[[], int] | None = None,
    ) -> None:
        self.tcp_port = tcp_port
        self.server_name = server_name
        self.discovery_port = discovery_port
        self.use_tls = use_tls
        self.get_players_count = get_players_count or (lambda: 0)

        self._running = False
        self._thread: threading.Thread | None = None
        self._sockets: list[socket.socket] = []

    def start(self) -> None:
        """Démarre le répondeur de découverte dans un thread daemon."""
        if self._running:
            return

        self._running = True
        self._sockets = self._create_listener_sockets()
        self._thread = threading.Thread(target=self._run_loop, name="DiscoveryServer", daemon=True)
        self._thread.start()
        logger.info(f"[DISCOVERY] Répondeur démarré sur le port UDP {self.discovery_port}")

    def stop(self) -> None:
        """Arrête proprement le répondeur et ferme les sockets UDP."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        for sock in self._sockets:
            try:
                sock.close()
            except OSError:
                pass
        self._sockets.clear()
        logger.info("[DISCOVERY] Répondeur arrêté.")

    def _create_listener_sockets(self) -> list[socket.socket]:
        """Initialise les sockets UDP Multicast IPv4 et IPv6."""
        sockets = []

        # 1. Socket IPv4 Multicast & Broadcast
        try:
            s4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s4.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            except OSError:
                pass
            s4.bind(("", self.discovery_port))

            # Adhésion au groupe Multicast IPv4
            mreq4 = struct.pack(
                "4sL",
                socket.inet_aton(MULTICAST_IPV4_GROUP),
                socket.INADDR_ANY,
            )
            s4.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq4)
            sockets.append(s4)
        except Exception as exc:
            logger.debug(f"[DISCOVERY] Socket IPv4 non disponible : {exc}")

        # 2. Socket IPv6 Multicast (Link-Local)
        try:
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s6.bind(("::", self.discovery_port))

            # Adhésion au groupe Multicast IPv6
            group_bin = socket.inet_pton(socket.AF_INET6, MULTICAST_IPV6_GROUP)
            mreq6 = group_bin + struct.pack("@I", 0)
            s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP, mreq6)
            sockets.append(s6)
        except Exception as exc:
            logger.debug(f"[DISCOVERY] Socket IPv6 non disponible : {exc}")

        return sockets

    def _run_loop(self) -> None:
        """Boucle d'écoute non-bloquante via select."""
        while self._running and self._sockets:
            try:
                readable, _, _ = select.select(self._sockets, [], [], 0.5)
                for sock in readable:
                    data, addr = sock.recvfrom(2048)
                    self._handle_datagram(sock, data, addr)
            except OSError:
                break
            except Exception as exc:
                logger.debug(f"[DISCOVERY] Erreur lors de la réception : {exc}")

    def _handle_datagram(self, sock: socket.socket, data: bytes, sender_addr: tuple) -> None:
        """Traite une sonde reçue et envoie l'offre en Unicast vers l'émetteur."""
        try:
            msg = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return

        if not isinstance(msg, dict) or msg.get("type") != "DISCOVER":
            return

        offer = {
            "type": "OFFER",
            "server_name": self.server_name,
            "tcp_port": self.tcp_port,
            "players_count": self.get_players_count(),
            "use_tls": self.use_tls,
        }
        raw_offer = json.dumps(offer).encode("utf-8")
        print(f"[DISCOVERY] Sonde reçue de {sender_addr}, envoi offre ({self.server_name}:{self.tcp_port})...")

        try:
            sock.sendto(raw_offer, sender_addr)
            print(f"[DISCOVERY] Offre envoyée avec succès à {sender_addr}")
        except OSError as exc:
            print(f"[DISCOVERY] Échec envoi OFFER vers {sender_addr} : {exc}")


def discover_servers(
    timeout: float = 1.2,
    discovery_port: int = DEFAULT_DISCOVERY_PORT,
) -> list[dict[str, Any]]:
    """
    Sonde le réseau local en envoyant des requêtes Multicast UDP (IPv4 et IPv6)
    et collecte l'ensemble des réponses pendant le délai imparti.

    Retourne une liste de dictionnaires décrivant chaque serveur découvert :
    [
        {
            "ip": "192.168.1.42",
            "port": 8888,
            "server_name": "Serveur Pendu M1",
            "players_count": 2,
            "use_tls": False,
            "display": "Serveur Pendu M1 — 192.168.1.42:8888 (2 joueurs)"
        },
        ...
    ]
    """
    sockets: list[socket.socket] = []
    probe_msg = json.dumps({"type": "DISCOVER"}).encode("utf-8")

    # 1. Socket de sondage IPv4 (Multicast + Broadcast)
    s4 = None
    try:
        s4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s4.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s4.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        s4.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        sockets.append(s4)
    except OSError:
        pass

    # 2. Socket de sondage IPv6 (Multicast Link-Local)
    s6 = None
    try:
        s6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 1)
        s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_LOOP, 1)
        sockets.append(s6)
    except OSError:
        pass

    if not sockets:
        return []

    # Émission des sondes sur les canaux multicast et broadcast
    if s4:
        try:
            s4.sendto(probe_msg, (MULTICAST_IPV4_GROUP, discovery_port))
        except OSError:
            pass
        try:
            # Diffusion générale de secours (255.255.255.255)
            s4.sendto(probe_msg, ("<broadcast>", discovery_port))
        except OSError:
            pass
        try:
            # Diffusion ciblée : Broadcast dirigé ET Balayage Unicast de sous-réseau
            # Contourne 100% des restrictions de la box (pas besoin de toucher à la box !)
            _, _, ips = socket.gethostbyname_ex(socket.gethostname())
            for ip in ips:
                parts = ip.split(".")
                if len(parts) == 4 and not ip.startswith("127."):
                    # 1. Broadcast dirigé
                    try:
                        s4.sendto(probe_msg, (f"{parts[0]}.{parts[1]}.{parts[2]}.255", discovery_port))
                    except OSError:
                        pass
                    # 2. Balayage Unicast direct (ignoré par les filtres multicast des box)
                    prefix = f"{parts[0]}.{parts[1]}.{parts[2]}"
                    for host_id in range(1, 255):
                        try:
                            s4.sendto(probe_msg, (f"{prefix}.{host_id}", discovery_port))
                        except OSError:
                            pass
        except Exception:
            pass

    if s6:
        try:
            s6.sendto(probe_msg, (MULTICAST_IPV6_GROUP, discovery_port))
        except OSError:
            pass

    # Collecte des réponses avec déduplication
    discovered: dict[str, dict[str, Any]] = {}
    deadline = time.monotonic() + timeout

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            readable, _, _ = select.select(sockets, [], [], min(remaining, 0.2))
            for sock in readable:
                try:
                    data, addr = sock.recvfrom(2048)
                    raw_ip = addr[0]
                    # Nettoyage de l'éventuel identifiant de zone scope IPv6 (ex: fe80::1%12 -> fe80::1)
                    clean_ip = raw_ip.split("%")[0]

                    resp = json.loads(data.decode("utf-8"))
                    if isinstance(resp, dict) and resp.get("type") == "OFFER":
                        tcp_port = int(resp.get("tcp_port", 8888))
                        server_name = str(resp.get("server_name", "Serveur Pendu"))
                        players = int(resp.get("players_count", 0))
                        use_tls = bool(resp.get("use_tls", False))

                        key = f"{clean_ip}:{tcp_port}"
                        if key not in discovered:
                            tls_badge = " [TLS 🔒]" if use_tls else ""
                            display_str = f"{server_name}{tls_badge} — {clean_ip}:{tcp_port} ({players} joueur{'s' if players > 1 else ''})"
                            discovered[key] = {
                                "ip": clean_ip,
                                "port": tcp_port,
                                "server_name": server_name,
                                "players_count": players,
                                "use_tls": use_tls,
                                "display": display_str,
                            }
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OSError):
                    continue
    finally:
        for sock in sockets:
            try:
                sock.close()
            except OSError:
                pass

    return list(discovered.values())
