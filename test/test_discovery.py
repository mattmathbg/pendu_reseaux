import time
import socket
import pytest
from protocol.discovery import (
    DiscoveryServer,
    discover_servers,
    DEFAULT_DISCOVERY_PORT,
    MULTICAST_IPV4_GROUP,
)


def test_discovery_server_lifecycle():
    """Vérifie le démarrage et l'arrêt propre du DiscoveryServer."""
    srv = DiscoveryServer(tcp_port=9999, server_name="Test Lifecycle")
    srv.start()
    assert srv._running is True
    assert len(srv._sockets) > 0

    srv.stop()
    assert srv._running is False
    assert len(srv._sockets) == 0


def test_discovery_end_to_end():
    """Vérifie la découverte de bout en bout d'un serveur via Multicast UDP."""
    # Port UDP dédié pour isoler le test unitaire
    test_udp_port = 8895
    srv = DiscoveryServer(
        tcp_port=8888,
        server_name="Serveur Défi M1",
        discovery_port=test_udp_port,
        use_tls=True,
        get_players_count=lambda: 3,
    )
    srv.start()
    time.sleep(0.1)

    try:
        found = discover_servers(timeout=1.0, discovery_port=test_udp_port)
        assert len(found) >= 1
        matched = [s for s in found if s["server_name"] == "Serveur Défi M1"]
        assert 1 <= len(matched) <= 2  # Découvert en IPv4 et/ou IPv6
        s = matched[0]
        assert s["port"] == 8888
        assert s["players_count"] == 3
        assert s["use_tls"] is True
        assert "Serveur Défi M1" in s["display"]
        assert "[TLS 🔒]" in s["display"]
    finally:
        srv.stop()


def test_discovery_timeout_when_no_server():
    """Vérifie que la fonction de découverte renvoie une liste vide après timeout."""
    found = discover_servers(timeout=0.3, discovery_port=8896)
    assert found == []


def test_discovery_ignores_invalid_packet():
    """Vérifie que le répondeur ignore silencieusement les paquets invalides."""
    test_udp_port = 8897
    srv = DiscoveryServer(tcp_port=8888, discovery_port=test_udp_port)
    srv.start()
    time.sleep(0.1)

    try:
        # Envoi d'un paquet corrompu / non JSON
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(b"NOT_A_JSON_PACKET", (MULTICAST_IPV4_GROUP, test_udp_port))
        sock.sendto(b'{"type":"OTHER_TYPE"}', (MULTICAST_IPV4_GROUP, test_udp_port))
        sock.close()

        # Le serveur doit continuer à fonctionner et répondre à un DISCOVER valide
        found = discover_servers(timeout=1.0, discovery_port=test_udp_port)
        assert len(found) >= 1
    finally:
        srv.stop()
