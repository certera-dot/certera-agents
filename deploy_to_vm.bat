@echo off
echo ====================================================
echo  DEPLOY trading-agent a VM Oracle 137.131.187.213
echo ====================================================

set KEY="C:\Users\martin\Downloads\ssh-key-2026-05-07 (1).key"
set VM=ubuntu@137.131.187.213
set SRC="C:\Users\martin\Desktop\AGENCIA IA\trading-agent"

echo.
echo [1/5] Copiando archivos a la VM...
scp -i %KEY% -o StrictHostKeyChecking=no -r %SRC% %VM%:/home/ubuntu/trading-agent-src
if %ERRORLEVEL% neq 0 ( echo ERROR en scp & pause & exit /b 1 )

echo.
echo [2/5] Bootstrap (instala Python, crea usuario trader, carpetas)...
ssh -i %KEY% -o StrictHostKeyChecking=no %VM% "sudo bash /home/ubuntu/trading-agent-src/deploy/bootstrap_vm.sh"
if %ERRORLEVEL% neq 0 ( echo ERROR en bootstrap & pause & exit /b 1 )

echo.
echo [3/5] Copiando codigo a /opt/trading-agent...
ssh -i %KEY% -o StrictHostKeyChecking=no %VM% "sudo cp -r /home/ubuntu/trading-agent-src/. /opt/trading-agent/ && sudo chown -R trader:trader /opt/trading-agent"
if %ERRORLEVEL% neq 0 ( echo ERROR copiando a /opt & pause & exit /b 1 )

echo.
echo [4/5] Instalando dependencias y servicio systemd...
ssh -i %KEY% -o StrictHostKeyChecking=no %VM% "sudo bash /opt/trading-agent/deploy/install_service.sh"
if %ERRORLEVEL% neq 0 ( echo ERROR en install_service & pause & exit /b 1 )

echo.
echo [5/5] Estado del agente:
ssh -i %KEY% -o StrictHostKeyChecking=no %VM% "sudo systemctl status trading-agent --no-pager -l"

echo.
echo ====================================================
echo  LISTO. Para ver logs en vivo, correr en CMD:
echo  ssh -i %KEY% %VM% "sudo journalctl -fu trading-agent"
echo ====================================================
pause
