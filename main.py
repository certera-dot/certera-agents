"""
TRADING AGENT — Punto de entrada principal
==========================================
Inicializa todos los módulos y arranca el agente
según el modo de operación configurado.

Mercados soportados:
  - Binance  (Crypto Spot)       — siempre activo
  - Forex    (CCXT/currencycom)  — activo si FOREX_ENABLED=true
  - Alpaca   (NYSE/NASDAQ)       — activo si ALPACA_API_KEY configurada
"""

import asyncio
import os
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

from core.engine import TradingEngine
from core.risk_manager import RiskManager
from core.learning_engine import LearningEngine
from connectors.binance import BinanceConnector
from connectors.forex import ForexConnector
from connectors.alpaca import AlpacaConnector
from tg_bot.bot import TelegramBot
from database.supabase import SupabaseClient


async def _connect(name: str, connector, bot: TelegramBot, engine: TradingEngine) -> None:
    """Conecta un conector de forma tolerante a fallos (regla #4 CLAUDE.md)."""
    ok = await connector.connect()
    engine.register_connector(name, connector)
    if ok:
        logger.info(f"Connector '{name}' registrado OK")
    else:
        await bot.send_message(
            f"⚠️ <b>{name.capitalize()}</b> no disponible al arrancar — "
            f"el agente continúa sin él."
        )


async def main():
    logger.info("=" * 60)
    logger.info("  TRADING AGENT — Iniciando...")
    logger.info(f"  Modo:       {os.getenv('OPERATION_MODE', 'manual').upper()}")
    logger.info(f"  Simulación: {os.getenv('SIMULATION_MODE', 'true')}")
    logger.info(f"  Madurez:    {os.getenv('AGENT_MATURITY_LEVEL', 'aprendiz')}")
    logger.info("=" * 60)

    # ── Componentes core ────────────────────────────────────────────────
    db     = SupabaseClient()
    risk   = RiskManager()
    learn  = LearningEngine(db=db)
    bot    = TelegramBot()
    engine = TradingEngine(
        risk_manager=risk,
        learning_engine=learn,
        telegram_bot=bot,
        db=db,
    )

    # ── Conectar exchanges en paralelo (tolerante a fallos) ─────────────
    connectors = [
        ("binance", BinanceConnector()),
        ("forex",   ForexConnector()),
        ("alpaca",  AlpacaConnector()),
    ]
    await asyncio.gather(*[
        _connect(name, conn, bot, engine) for name, conn in connectors
    ])

    # ── Notificación de inicio ──────────────────────────────────────────
    activos = [n for n in engine.connectors if engine.connectors[n].is_connected()]
    await bot.send_message(
        f"✅ <b>Trading Agent ONLINE</b>\n"
        f"Modo: <code>{os.getenv('OPERATION_MODE', 'manual').upper()}</code> | "
        f"Sim: <code>{os.getenv('SIMULATION_MODE', 'true')}</code>\n"
        f"Mercados activos: <code>{', '.join(activos) if activos else 'ninguno'}</code>\n\n"
        f"Probá <code>/status</code> o <code>/precio BTC</code>"
    )

    # ── Arrancar el agente ──────────────────────────────────────────────
    await asyncio.gather(
        engine.run(),
        bot.run(),
    )


if __name__ == "__main__":
    asyncio.run(main())
