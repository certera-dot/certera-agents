"""
Telegram bot — alertas de señales, comandos de control del agente.
Usa python-telegram-bot v20 (async).
"""
import asyncio
import os
from loguru import logger

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    _TG_AVAILABLE = True
except ImportError:
    _TG_AVAILABLE = False


class TelegramBot:
    def __init__(self):
        self.token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.app     = None
        self._engine_ref = None  # set after engine init

        if not _TG_AVAILABLE:
            logger.warning("Telegram: paquete no disponible")
            return
        if not self.token or "your_" in self.token:
            logger.warning("Telegram: token no configurado")
            return

        self.app = (
            Application.builder()
            .token(self.token)
            .build()
        )
        self._register_commands()
        logger.info("TelegramBot inicializado OK")

    def _register_commands(self):
        self.app.add_handler(CommandHandler("start",  self._cmd_start))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("pause",  self._cmd_pause))
        self.app.add_handler(CommandHandler("resume", self._cmd_resume))
        self.app.add_handler(CommandHandler("precio", self._cmd_precio))
        self.app.add_handler(CommandHandler("help",   self._cmd_help))

    async def send_message(self, text: str) -> None:
        if not self.app or not self.chat_id:
            logger.info(f"[TG-mock] {text}")
            return
        try:
            await self.app.bot.send_message(chat_id=self.chat_id, text=text,
                                             parse_mode="HTML")
        except Exception as e:
            logger.error(f"Telegram send_message: {e}")

    async def send_signal_alert(self, signal: dict, validation) -> None:
        status     = "✅ APROBADA" if validation.approved else f"❌ RECHAZADA ({validation.reason})"
        stype      = signal.get("signal_type", "?")
        asset      = signal.get("asset", "?")
        methodology = signal.get("methodology", "?")
        confidence  = signal.get("confidence", 0)
        timeframe   = signal.get("timeframe", "?")

        # Icono según metodología
        method_icons = {
            "ema_cross":     "📈",
            "rsi_oversold":  "🟢",
            "rsi_overbought":"🔴",
        }
        icon = method_icons.get(methodology, "📊")

        # Confidence en barras visuales
        bars = int(confidence * 10)
        conf_bar = "▓" * bars + "░" * (10 - bars)

        tps = signal.get("take_profit", [])
        tp_text = " / ".join(f"<code>{tp}</code>" for tp in tps) if tps else "N/A"

        text = (
            f"{icon} <b>SEÑAL {stype} — {asset}</b>\n"
            f"Setup: <code>{methodology}</code> | TF: <code>{timeframe}</code>\n"
            f"Confianza: {conf_bar} {confidence:.0%}\n"
            f"───────────────\n"
            f"Entry: <code>{signal.get('entry')}</code>\n"
            f"Stop:  <code>{signal.get('stop_loss')}</code>\n"
            f"TPs:   {tp_text}\n"
            f"───────────────\n"
            f"Estado: {status}"
        )
        await self.send_message(text)

    async def run(self) -> None:
        if not self.app:
            logger.warning("Telegram bot no activo — corriendo en modo silencioso")
            await asyncio.Event().wait()
            return
        try:
            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram bot polling activo")
            await asyncio.Event().wait()
        finally:
            if self.app.updater.running:
                await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    # ── Handlers de comandos ─────────────────────────────────────────────

    async def _cmd_start(self, update: "Update", ctx: "ContextTypes.DEFAULT_TYPE"):
        await update.message.reply_text(
            "🤖 <b>Trading Agent activo</b>\n\n"
            "/status — Estado del agente\n"
            "/precio BTC — Precio actual\n"
            "/pause — Pausar operaciones\n"
            "/resume — Reanudar operaciones\n"
            "/help — Ayuda",
            parse_mode="HTML"
        )

    async def _cmd_status(self, update: "Update", ctx: "ContextTypes.DEFAULT_TYPE"):
        if self._engine_ref:
            st = self._engine_ref.get_status()
            text = (
                f"<b>Estado del agente</b>\n"
                f"Modo: <code>{st['mode']}</code>\n"
                f"Simulación: <code>{st['simulation']}</code>\n"
                f"Pausado: <code>{st['paused']}</code>\n"
                f"P&L diario: <code>{st['daily_pnl_pct']:+.2f}%</code>\n"
                f"Drawdown: <code>{st['drawdown_pct']:.2f}%</code>"
            )
        else:
            text = "Agente activo — sin datos de engine disponibles."
        await update.message.reply_text(text, parse_mode="HTML")

    async def _cmd_pause(self, update: "Update", ctx: "ContextTypes.DEFAULT_TYPE"):
        if self._engine_ref:
            self._engine_ref.risk_manager.kill_switch()
            await update.message.reply_text("⏸ Agente pausado (kill switch activado).")
        else:
            await update.message.reply_text("Engine no disponible.")

    async def _cmd_resume(self, update: "Update", ctx: "ContextTypes.DEFAULT_TYPE"):
        if self._engine_ref:
            self._engine_ref.risk_manager.resume()
            await update.message.reply_text("▶️ Agente reanudado.")
        else:
            await update.message.reply_text("Engine no disponible.")

    async def _cmd_precio(self, update: "Update", ctx: "ContextTypes.DEFAULT_TYPE"):
        symbol = (ctx.args[0].upper() + "USDT") if ctx.args else "BTCUSDT"
        if self._engine_ref and "binance" in self._engine_ref.connectors:
            try:
                price = await self._engine_ref.connectors["binance"].get_price(symbol)
                await update.message.reply_text(f"💰 {symbol}: <code>${price:,.2f}</code>",
                                                 parse_mode="HTML")
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")
        else:
            await update.message.reply_text("Connector Binance no disponible.")

    async def _cmd_help(self, update: "Update", ctx: "ContextTypes.DEFAULT_TYPE"):
        await self._cmd_start(update, ctx)
