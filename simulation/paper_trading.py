"""
Paper Trading — gestiona el ciclo de vida completo de los trades simulados.

Sin esto, el agente detecta señales pero nunca sabe si hubieran funcionado:
abre una posición simulada cuando una señal es aprobada, la monitorea cada
scan, y la cierra cuando el precio toca TP1 (WIN), el stop (LOSS), o pasa
demasiado tiempo sin definirse (BREAKEVEN por timeout). Sin trades cerrados
con resultado real no hay nada que learning_engine pueda aprender.
"""
from datetime import datetime, timezone
from loguru import logger


class PaperTradingManager:
    # Cierre forzado si nunca toca TP/SL — evita posiciones colgadas
    # indefinidamente (ej. forex cerrado el fin de semana).
    MAX_DURATION_HOURS = 48

    def __init__(self, db):
        self.db = db

    async def open_trade(self, signal: dict, market: str, extra: dict | None = None) -> dict | None:
        """Crea un trade en estado OPEN a partir de una señal ya aprobada
        por el RiskManager. Solo se llama en modo AUTO + simulación."""
        trade = {
            "mode":              "simulation",
            "asset":             signal["asset"],
            "timeframe":         signal.get("timeframe", "1h"),
            "session":           (extra or {}).get("session"),
            "day_of_week":       datetime.now(timezone.utc).strftime("%A"),
            "methodology":       signal.get("methodology"),
            "entry":             signal["entry"],
            "stop_loss":         signal["stop_loss"],
            "take_profit":       signal["take_profit"],
            "result":            "OPEN",
            "agent_confidence":  signal.get("confidence"),
            "confidence_adjusted": signal.get("confidence_adjusted", signal.get("confidence")),
            "risk_reward":       signal.get("min_rr", 2.0),
            "market_context":    {"market": market, "signal_type": signal["signal_type"]},
            "timestamp_open":    datetime.now(timezone.utc).isoformat(),
        }
        saved = await self.db.log_trade(trade)
        if saved:
            logger.info(f"Trade abierto | {signal['asset']} {signal['signal_type']} "
                        f"entry={signal['entry']} id={str(saved.get('id', '?'))[:8]}")
        return saved

    async def check_open_trades(self, connectors: dict) -> list:
        """Revisa todos los trades OPEN contra el precio actual, cierra los
        que tocaron TP1, stop, o vencieron por timeout. Retorna la lista de
        trades recién cerrados (con su resultado ya aplicado)."""
        open_trades = await self.db.get_open_trades()
        closed = []
        for trade in open_trades:
            try:
                price = await self._get_price(trade["asset"], connectors)
                if not price or price <= 0:
                    continue
                outcome = self._evaluate(trade, price)
                if outcome:
                    updated = await self._close_trade(trade, price, outcome)
                    if updated:
                        closed.append(updated)
            except Exception as e:
                logger.error(f"check_open_trades error en {trade.get('asset')}: {e}")
        return closed

    def _evaluate(self, trade: dict, price: float) -> dict | None:
        """Decide si el trade debe cerrarse ahora. None = sigue abierto."""
        direction = trade.get("market_context", {}).get("signal_type", "LONG")
        stop      = float(trade["stop_loss"])
        tps       = trade["take_profit"]
        tp1       = float(tps[0]) if isinstance(tps, list) else float(tps)

        if direction == "LONG":
            if price >= tp1:
                return {"result": "WIN", "exit_reason": "tp1_hit"}
            if price <= stop:
                return {"result": "LOSS", "exit_reason": "stop_hit"}
        else:  # SHORT
            if price <= tp1:
                return {"result": "WIN", "exit_reason": "tp1_hit"}
            if price >= stop:
                return {"result": "LOSS", "exit_reason": "stop_hit"}

        hours_open = self._hours_open(trade)
        if hours_open is not None and hours_open >= self.MAX_DURATION_HOURS:
            return {"result": "BREAKEVEN", "exit_reason": "timeout_48h"}
        return None

    async def _close_trade(self, trade: dict, exit_price: float, outcome: dict) -> dict | None:
        direction = trade.get("market_context", {}).get("signal_type", "LONG")
        entry     = float(trade["entry"])
        pnl_pct   = ((exit_price - entry) / entry * 100 if direction == "LONG"
                     else (entry - exit_price) / entry * 100)

        hours_open = self._hours_open(trade)
        duration   = int(hours_open * 60) if hours_open is not None else None

        updates = {
            "result":           outcome["result"],
            "exit_reason":      outcome["exit_reason"],
            "exit_price":       exit_price,
            "pnl_pct":          round(pnl_pct, 4),
            "duration_minutes": duration,
            "timestamp_close":  datetime.now(timezone.utc).isoformat(),
        }
        updated = await self.db.update_trade(trade["id"], updates)
        if updated:
            logger.info(f"Trade cerrado | {trade['asset']} {outcome['result']} "
                        f"pnl={pnl_pct:+.2f}% razón={outcome['exit_reason']}")
            return {**trade, **updates}
        return None

    def _hours_open(self, trade: dict) -> float | None:
        opened = trade.get("timestamp_open")
        if not opened:
            return None
        opened_dt = datetime.fromisoformat(opened.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - opened_dt).total_seconds() / 3600

    async def _get_price(self, asset: str, connectors: dict) -> float | None:
        try:
            if "/" in asset and "forex" in connectors and connectors["forex"].is_connected():
                return await connectors["forex"].get_price(asset)
            # Stocks de Alpaca: símbolos sin "/" y sin sufijos como USDT
            if ("alpaca" in connectors and connectors["alpaca"].is_connected()
                    and not any(asset.endswith(s) for s in ("USDT", "BTC", "ETH", "BNB"))):
                return await connectors["alpaca"].get_price(asset)
            if "binance" in connectors and connectors["binance"].is_connected():
                return await connectors["binance"].get_price(asset)
        except Exception as e:
            logger.error(f"_get_price error en {asset}: {e}")
        return None
