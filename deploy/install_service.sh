#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  INSTALL_SERVICE — corre EN la VM, después de subir el código
#  - Crea el venv en /opt/trading-agent/venv
#  - Instala dependencias
#  - Activa systemd para auto-start al boot + auto-restart
# ─────────────────────────────────────────────────────────────
set -euo pipefail

AGENT_DIR=/opt/trading-agent

echo "==> Verificando que existe $AGENT_DIR/main.py y .env..."
test -f "$AGENT_DIR/main.py" || { echo "ERROR: falta $AGENT_DIR/main.py"; exit 1; }
test -f "$AGENT_DIR/.env"    || { echo "ERROR: falta $AGENT_DIR/.env";    exit 1; }
test -f "$AGENT_DIR/requirements.txt" || { echo "ERROR: falta requirements.txt"; exit 1; }

echo "==> Asegurando ownership a 'trader'..."
chown -R trader:trader "$AGENT_DIR"

echo "==> Creando virtualenv (como user trader)..."
sudo -u trader bash -c "
    cd $AGENT_DIR
    if [ ! -d venv ]; then
        python3 -m venv venv
    fi
    source venv/bin/activate
    pip install --upgrade pip wheel
    pip install -r requirements.txt
"

echo "==> Instalando systemd unit..."
cp "$AGENT_DIR/deploy/trading-agent.service" /etc/systemd/system/trading-agent.service
chmod 644 /etc/systemd/system/trading-agent.service

systemctl daemon-reload
systemctl enable trading-agent.service
systemctl restart trading-agent.service

sleep 4
echo
echo "==> Estado del servicio:"
systemctl status trading-agent.service --no-pager -l || true
echo
echo "==> Para ver logs en vivo:    journalctl -u trading-agent -f"
echo "==> Para reiniciar:           sudo systemctl restart trading-agent"
echo "==> Para detener:             sudo systemctl stop trading-agent"
