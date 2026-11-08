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

# Écoute sur 0.0.0.0 pour être accessible depuis l'hôte
CMD ["python", "-m", "server.server", "--host", "0.0.0.0", "--port", "8888"]