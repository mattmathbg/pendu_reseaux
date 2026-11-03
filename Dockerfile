FROM python:3.11-slim

# Empêche Python de mettre en mémoire tampon stdout/stderr (logs en temps réel)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copie uniquement des modules nécessaires à l'exécution
COPY core/ ./core/
COPY protocol/ ./protocol/
COPY server/ ./server/
COPY client/ ./client/

# Documentation du port applicatif écouté par le conteneur
EXPOSE 8888/tcp

# Commande par défaut (Serveur écoutant sur toutes les interfaces du conteneur)
CMD ["python", "-m", "server.server", "--host", "0.0.0.0", "--port", "8888"]