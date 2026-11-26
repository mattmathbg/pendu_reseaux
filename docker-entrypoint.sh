#!/bin/sh
set -e

CERT_FILE="${SSL_CERT_FILE:-/app/certs/server.crt}"
KEY_FILE="${SSL_KEY_FILE:-/app/certs/server.key}"

if [ ! -f "$KEY_FILE" ] || [ ! -f "$CERT_FILE" ]; then
    CERT_DIR="$(dirname "$KEY_FILE")"
    if mkdir -p "$CERT_DIR" 2>/dev/null && touch "$CERT_DIR/.write_test" 2>/dev/null; then
        rm -f "$CERT_DIR/.write_test"
        TARGET_CERT="$CERT_FILE"
        TARGET_KEY="$KEY_FILE"
    else
        mkdir -p /tmp/certs
        TARGET_CERT="/tmp/certs/server.crt"
        TARGET_KEY="/tmp/certs/server.key"
        export SSL_CERT_FILE="$TARGET_CERT"
        export SSL_KEY_FILE="$TARGET_KEY"
    fi

    echo "[DOCKER] Certificat ou cle TLS absent : generation auto-signee ($(dirname "$TARGET_KEY"))..."
    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "$TARGET_KEY" \
        -out "$TARGET_CERT" \
        -days 365 \
        -subj "/CN=localhost" >/dev/null 2>&1
fi

exec "$@"
