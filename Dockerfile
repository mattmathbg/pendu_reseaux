FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY core/ ./core/
COPY protocol/ ./protocol/
COPY server/ ./server/
COPY client/ ./client/
COPY certs/ ./certs/

EXPOSE 8888/tcp

# En omettant --host (avec default=None dans server.py), le serveur écoute en IPv4 ET IPv6
CMD ["python", "-m", "server.server", "--port", "8888"]