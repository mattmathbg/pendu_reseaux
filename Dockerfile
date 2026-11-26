FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*

COPY core/ ./core/
COPY protocol/ ./protocol/
COPY server/ ./server/
COPY client/ ./client/
COPY certs/ ./certs/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8888/tcp 8889/udp

# Écoute sur 0.0.0.0 et :: (dual-stack IPv4/IPv6) avec TLS activé par défaut.
# Génère automatiquement une paire auto-signée si server.key est absente.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "server.server", "--port", "8888", "--tls"]