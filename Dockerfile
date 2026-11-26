FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY core/ ./core/
COPY protocol/ ./protocol/
COPY server/ ./server/
COPY client/ ./client/
COPY certs/ ./certs/

EXPOSE 8888/tcp 8889/udp

# Écoute sur 0.0.0.0 et :: (dual-stack IPv4/IPv6) par défaut.
# Active TLS si la clé privée est montée (/app/certs/server.key ou SSL_KEY_FILE),
# sinon bascule sur --no-tls pour que l'image publiée démarre sans erreur.
CMD ["sh", "-c", "if [ -f \"${SSL_KEY_FILE:-/app/certs/server.key}\" ]; then exec python -m server.server --port 8888 --tls; else echo '[DOCKER] Cle TLS absente : demarrage sans TLS (--no-tls). Montez -v ./certs:/app/certs:ro pour activer TLS.'; exec python -m server.server --port 8888 --no-tls; fi"]