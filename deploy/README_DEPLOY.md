# Deploy a Oracle Cloud Free Tier

Esta guía deja el agente corriendo 24/7 en una VM ARM gratis de Oracle.

## Requisitos previos

- Cuenta Oracle Cloud activada (plan Always Free).
- VM ARM Ampere creada con Ubuntu 22.04 o Oracle Linux 9.
- Clave SSH descargada (`oracle_trading.key`).
- IP pública de la VM.

## Orden de ejecución

### 1. Subir bootstrap a la VM (desde tu PC)

```bash
scp -i ~/.ssh/oracle_trading.key deploy/bootstrap_vm.sh opc@TU_IP:/tmp/
ssh -i ~/.ssh/oracle_trading.key opc@TU_IP "sudo bash /tmp/bootstrap_vm.sh"
```

### 2. Subir el código por primera vez

Editá `deploy/update.sh` con tu IP, usuario y ruta de la clave, después:

```bash
bash deploy/update.sh
```

(La primera vez fallará el `restart` porque todavía no hay servicio — ignorá ese error.)

### 3. Subir el `.env` (manualmente, NO va por rsync por seguridad)

```bash
scp -i ~/.ssh/oracle_trading.key .env opc@TU_IP:/tmp/.env
ssh -i ~/.ssh/oracle_trading.key opc@TU_IP "sudo mv /tmp/.env /opt/trading-agent/.env && sudo chown trader:trader /opt/trading-agent/.env && sudo chmod 600 /opt/trading-agent/.env"
```

### 4. Instalar el servicio

```bash
ssh -i ~/.ssh/oracle_trading.key opc@TU_IP "sudo bash /opt/trading-agent/deploy/install_service.sh"
```

A partir de acá el agente queda corriendo, se autoreinicia si crashea, y arranca solo al reboot de la VM.

## Operación diaria

```bash
# Ver logs en vivo
ssh -i ~/.ssh/oracle_trading.key opc@TU_IP "sudo journalctl -u trading-agent -f"

# Reiniciar manualmente
ssh -i ~/.ssh/oracle_trading.key opc@TU_IP "sudo systemctl restart trading-agent"

# Subir cambios de código
bash deploy/update.sh
```

## Control desde Telegram

El agente queda escuchando comandos en tu chat:

- `/status` — estado actual
- `/precio BTC` — precio en vivo
- `/pause` — kill switch
- `/resume` — reanudar
- `/help` — ayuda
