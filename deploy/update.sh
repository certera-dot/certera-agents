#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  UPDATE — corre desde TU PC (Windows con Git Bash o WSL)
#  Sincroniza código local → VM Oracle, reinicia el servicio.
#
#  Uso:  ./deploy/update.sh
#
#  Configurá las variables abajo o exportalas en tu shell.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

# ─── Config — EDITAR estas tres líneas con los datos de tu VM ─────────
VM_USER="${VM_USER:-opc}"                          # 'opc' en Oracle Linux, 'ubuntu' en Ubuntu
VM_HOST="${VM_HOST:-XX.XX.XX.XX}"                  # IP pública de la VM
SSH_KEY="${SSH_KEY:-$HOME/.ssh/oracle_trading.key}" # Ruta a tu clave privada SSH
# ──────────────────────────────────────────────────────────────────────

LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_DIR="/opt/trading-agent"

echo "==> Sincronizando código a $VM_USER@$VM_HOST:$REMOTE_DIR"

# rsync excluye lo que NO debe ir al servidor
rsync -avz --delete \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    --exclude='venv/' \
    --exclude='logs/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.git/' \
    --exclude='binance_testnet_keys_BACKUP.txt' \
    --exclude='dashboard/node_modules/' \
    --exclude='dashboard/dist/' \
    "$LOCAL_DIR/" "$VM_USER@$VM_HOST:/tmp/trading-agent-staging/"

echo "==> Aplicando cambios y reiniciando servicio en la VM..."
ssh -i "$SSH_KEY" "$VM_USER@$VM_HOST" bash -s <<'REMOTE'
set -euo pipefail
sudo rsync -a --delete \
    --exclude='venv/' \
    --exclude='logs/' \
    --exclude='.env' \
    /tmp/trading-agent-staging/ /opt/trading-agent/
sudo chown -R trader:trader /opt/trading-agent
# Si requirements.txt cambió, reinstalar dependencias
if [ /tmp/trading-agent-staging/requirements.txt -nt /opt/trading-agent/venv/.last-pip-install ]; then
    echo "==> requirements.txt cambió — reinstalando dependencias..."
    sudo -u trader bash -c "cd /opt/trading-agent && source venv/bin/activate && pip install -r requirements.txt"
    sudo -u trader touch /opt/trading-agent/venv/.last-pip-install
fi
sudo systemctl restart trading-agent
sleep 3
sudo systemctl status trading-agent --no-pager -l | head -15
REMOTE

echo
echo "==> Update completo. Para ver logs en vivo:"
echo "    ssh -i $SSH_KEY $VM_USER@$VM_HOST 'sudo journalctl -u trading-agent -f'"
