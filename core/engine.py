"""
Trading Engine — orquestador central del agente.
Coordina: detección de señales → validación de riesgo → notificación/ejecución.

Modos:
  MANUAL    → solo alertas Telegram, cero ejecución automática
  SEMI_AUTO → propone orden, espera confirmación Telegram (TODO: fase 2)
  AUTO      → ejecuta dentro de parámetros de RiskManager (TODO: fase 3)
"""
import asyncio
import os
from datetime import datetime
from loguru import logger

from core.risk_manager import RiskManager
from core.learning_engine import LearningEngine
from core.signal_detector import SignalDetector
from core.tech_lead_agent import TechLeadAgent
from execution.modes import OperationMode
from simulation.paper_trading import PaperTradingManager

# Cada cuántos trades cerrados se recalculan los pesos por patrón
PATTERN_WEIGHT_UPDATE_EVERY = 10


class TradingEngine:
    SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "300"))   # 5 min por defecto
    DAILY_RESET_HOUR  = 0                                             # medianoche UTC

    def __init__(self, risk_manager: RiskManager, learning_engine: LearningEngine,
                 telegram_bot, db):
        self.risk_manager    = risk_manager
        self.learning_engine = learning_engine
        self.bot             = telegram_bot
        self.db              = db
        self.connectors: dict = {}
        self.detector        = SignalDetector()
        self.paper_trading   = PaperTradingManager(db=db)

        self.mode       = OperationMode(os.getenv("OPERATION_MODE", "manual"))
        self.simulation = os.getenv("SIMULATION_MODE", "true").lower() == "true"

        self.tech_lead          = TechLeadAgent(db=db)
        self._consecutive_losses: dict = {}  # {setup: int} — actualizado tras cada trade cerrado

        # Backref en el bot para que los comandos /status, /pause, etc. funcionen
        if hasattr(telegram_bot, "_engine_ref"):
            telegram_bot._engine_ref = self

        logger.info(f"TradingEngine OK | modo={self.mode} | simulación={self.simulation}")

    def register_connector(self, name: str, connector) -> None:
        self.connectors[name] = connector
        logger.info(f"Connector registrado: {name}")

    def get_status(self) -> dict:
        rs = self.risk_manager.status
        return {
            "mode":          self.mode,
            "simulation":    self.simulation,
            "paused":        rs["paused"],
            "daily_pnl_pct": rs["daily_pnl_pct"],
            "drawdown_pct":  rs["drawdown_pct"],
            "connectors":    list(self.connectors.keys()),
        }

    async def run(self) -> None:
        logger.info("Engine loop iniciado")
        await self.bot.send_message(
            f"🚀 <b>Trading Agent arrancó</b>\n"
            f"Modo: <code>{self.mode}</code> | "
            f"Simulación: <code>{self.simulation}</code>"
        )

        last_reset_day = datetime.utcnow().date()

        while True:
            try:
                # ── Reset diario de P&L ──────────────────────────────────
                today = datetime.utcnow().date()
                if today != last_reset_day:
                    self.risk_manager.reset_daily()
                    last_reset_day = today
                    logger.info("Reset diario de P&L completado")

                if not self.risk_manager.is_paused:
                    # ── Monitorear trades simulados abiertos (TP/SL/timeout) ──
                    await self._monitor_open_trades()
                    # ── Scan de señales (todos los mercados activos) ──────────
                    await self._scan_all_markets()

                await asyncio.sleep(self.SCAN_INTERVAL_SEC)

            except asyncio.CancelledError:
                logger.info("Engine detenido")
                break
            except Exception as e:
                logger.error(f"Engine loop error: {e}")
                await asyncio.sleep(30)

    async def _scan_all_markets(self) -> None:
        """Escanea todos los mercados conectados en paralelo."""
        tasks = []
        if "binance" in self.connectors and self.connectors["binance"].is_connected():
            tasks.append(self._scan_crypto())
        if "forex" in self.connectors and self.connectors["forex"].is_connected():
            tasks.append(self._scan_forex())
        if "alpaca" in self.connectors and self.connectors["alpaca"].is_connected():
            tasks.append(self._scan_stocks())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _scan_crypto(self) -> None:
        binance = self.connectors["binance"]
        for symbol in self.detector.WATCHLIST:
            try:
                klines = await binance.get_klines(symbol, interval="1h", limit=100)
                await self._process_signal(symbol, klines, market="crypto")
            except Exception as e:
                logger.error(f"Error escaneando crypto {symbol}: {e}")

    async def _scan_forex(self) -> None:
        from connectors.forex import current_session
        forex = self.connectors["forex"]
        if not forex.is_market_open():
            logger.debug("Forex: mercado cerrado — scan omitido")
            return
        session = current_session()
        for pair in forex.watchlist:
            try:
                klines = await forex.get_klines(pair, timeframe="1h", limit=100)
                await self._process_signal(pair, klines, market="forex",
                                           extra={"session": session})
            except Exception as e:
                logger.error(f"Error escaneando forex {pair}: {e}")

    async def _scan_stocks(self) -> None:
        from connectors.alpaca import market_open
        if not market_open():
            logger.debug("Alpaca: mercado cerrado — scan omitido")
            return
        alpaca = self.connectors["alpaca"]
        for symbol in alpaca.watchlist:
            try:
                klines = await alpaca.get_klines(symbol, timeframe="1Hour", limit=100)
                await self._process_signal(symbol, klines, market="stocks")
            except Exception as e:
                logger.error(f"Error escaneando stock {symbol}: {e}")

    async def _process_signal(self, symbol: str, klines: list,
                               market: str = "crypto", extra: dict | None = None) -> None:
        signal = self.detector.detect(symbol, klines)
        if signal is None:
            return

        validation = self.risk_manager.validate(signal.to_dict())

        # confidence_adjusted: aplica el aprendizaje acumulado (weight_factor)
        # sobre la confianza cruda del detector. Sin trades cerrados todavía
        # el peso es neutro (1.0) y confidence_adjusted == confidence_raw.
        weight_factor       = await self.learning_engine.get_weight_factor(signal.methodology)
        confidence_adjusted = round(min(signal.confidence * weight_factor, 1.0), 2)

        await self.db.log_signal({
            "asset":              signal.asset,
            "timeframe":          signal.timeframe,
            "signal_type":        signal.signal_type,
            "entry":              signal.entry,
            "stop_loss":          signal.stop_loss,
            "take_profit":        signal.take_profit,
            "confidence_raw":     signal.confidence,
            "confidence_adjusted": confidence_adjusted,
            "methodology":        signal.methodology,   # ← bug fix: ya no llega NULL
            "pre_filter_passed":  validation.approved,
            "was_executed":       False,
            "market_context":     {
                **signal.indicators,
                "market":           market,
                **(extra or {}),
                "rejection_reason": str(validation.reason) if not validation.approved else None,
            },
        })

        # Tech Lead Agent: evalúa en shadow mode (no bloquea, solo informa)
        consecutive_losses = self._consecutive_losses.get(signal.methodology, 0)
        shadow = await self.tech_lead.evaluate(
            signal=signal.to_dict(),
            consecutive_losses=consecutive_losses,
            recent_trades=self.learning_engine._trade_log,
        )

        await self.bot.send_signal_alert(signal.to_dict(), validation, shadow_decision=shadow)
        analysis = await self.learning_engine.analyze_signal(signal.to_dict())
        if analysis and "offline" not in analysis.lower():
            await self.bot.send_message(f"🤖 <i>{analysis}</i>")

        # ── Abrir trade simulado para que el ciclo de aprendizaje tenga
        # un resultado real que medir (WIN/LOSS) más adelante ───────────
        if validation.approved and self.mode == OperationMode.AUTO and self.simulation:
            signal_dict = {**signal.to_dict(), "confidence_adjusted": confidence_adjusted}
            await self.paper_trading.open_trade(signal_dict, market=market, extra=extra)

        logger.info(f"Señal procesada | {market.upper()} {symbol} {signal.signal_type} "
                    f"aprobada={validation.approved} conf_adj={confidence_adjusted}")

    async def _monitor_open_trades(self) -> None:
        """Revisa los trades simulados abiertos, cierra los que tocaron
        TP/SL/timeout, y alimenta el resultado al ciclo de aprendizaje."""
        closed = await self.paper_trading.check_open_trades(self.connectors)
        for trade in closed:
            self.risk_manager.register_result(trade["result"], trade.get("pnl_pct", 0))
            await self.learning_engine.learn_from_trade(trade)
            await self._notify_trade_closed(trade)

            # Actualizar contador de pérdidas consecutivas por setup
            setup = trade.get("methodology", "unknown")
            if trade["result"] == "WIN":
                self._consecutive_losses[setup] = 0
            elif trade["result"] == "LOSS":
                self._consecutive_losses[setup] = self._consecutive_losses.get(setup, 0) + 1

        if not closed:
            return

        total_closed = await self.db.count_closed_trades()
        if total_closed and total_closed % PATTERN_WEIGHT_UPDATE_EVERY == 0:
            summary = await self.learning_engine.update_pattern_weights()
            if summary:
                lines = [f"• {m}: WR {d['win_rate']}% (n={d['sample_size']}) → peso {d['weight']}"
                         for m, d in summary.items()]
                await self.bot.send_message(
                    "📈 <b>Pesos de patrones actualizados</b>\n" + "\n".join(lines)
                )

    async def _notify_trade_closed(self, trade: dict) -> None:
        icon = {"WIN": "✅", "LOSS": "❌", "BREAKEVEN": "➖"}.get(trade["result"], "•")
        await self.bot.send_message(
            f"{icon} <b>Trade cerrado — {trade['asset']}</b>\n"
            f"Resultado: <code>{trade['result']}</code> | "
            f"P&L: <code>{trade.get('pnl_pct', 0):+.2f}%</code>\n"
            f"Razón: <code>{trade.get('exit_reason', '?')}</code>"
        )
