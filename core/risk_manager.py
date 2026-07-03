"""
RISK MANAGER — Módulo crítico de gestión de riesgo
===================================================
REGLA ABSOLUTA: Este módulo NUNCA puede ser modificado
por learning_engine ni por ningún módulo automático.
Todo orden pasa por validate() antes de ejecutarse.
"""

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from loguru import logger
from dotenv import load_dotenv

load_dotenv()


class RiskViolation(str, Enum):
    STOP_TOO_WIDE       = "stop_loss_excede_maximo"
    POSITION_TOO_LARGE  = "posicion_excede_maximo"
    DRAWDOWN_LIMIT      = "drawdown_diario_alcanzado"
    DAILY_LOSS_LIMIT    = "perdida_diaria_alcanzada"
    CONSECUTIVE_STOPS   = "3_stops_consecutivos"
    BAD_RR              = "riesgo_recompensa_insuficiente"
    NO_SIGNAL           = "señal_invalida_o_incompleta"
    NEWS_WINDOW         = "ventana_de_noticias"


@dataclass
class RiskValidationResult:
    approved: bool
    reason:   Optional[RiskViolation] = None
    message:  str = ""

    def __bool__(self):
        return self.approved


class RiskManager:
    def __init__(self):
        self.risk_per_trade_pct  = float(os.getenv("RISK_PER_TRADE_PCT",  "1.0"))
        self.stop_loss_max_pct   = float(os.getenv("STOP_LOSS_MAX_PCT",   "2.0"))
        self.position_size_max   = float(os.getenv("POSITION_SIZE_MAX_PCT","10.0"))
        self.drawdown_max_pct    = float(os.getenv("DRAWDOWN_MAX_PCT",    "15.0"))
        self.daily_loss_limit    = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "5.0"))

        self.daily_pnl_pct        = 0.0
        self.current_drawdown_pct = 0.0
        self.consecutive_stops    = 0
        self.is_paused            = False
        self.pause_reason         = None

        logger.info(f"RiskManager OK | riesgo/op:{self.risk_per_trade_pct}% drawdown_max:{self.drawdown_max_pct}%")

    def validate(self, signal: dict) -> RiskValidationResult:
        if self.is_paused:
            return RiskValidationResult(False, self.pause_reason, f"Agente pausado: {self.pause_reason}")

        required = ["asset", "signal_type", "entry", "stop_loss", "take_profit"]
        if not all(k in signal for k in required):
            return RiskValidationResult(False, RiskViolation.NO_SIGNAL, "Señal incompleta")

        entry     = float(signal["entry"])
        stop      = float(signal["stop_loss"])
        stop_dist = abs(entry - stop) / entry * 100

        if stop_dist > self.stop_loss_max_pct:
            return RiskValidationResult(False, RiskViolation.STOP_TOO_WIDE,
                f"Stop {stop_dist:.2f}% > max {self.stop_loss_max_pct}%")

        tp_list = signal["take_profit"]
        tp1     = float(tp_list[0]) if isinstance(tp_list, list) else float(tp_list)
        rr      = self._calc_rr(entry, stop, tp1, signal.get("signal_type","LONG"))
        min_rr  = signal.get("min_rr", 2.0)

        if rr < min_rr:
            return RiskValidationResult(False, RiskViolation.BAD_RR,
                f"R:R {rr:.2f} < mínimo {min_rr}")

        if abs(self.daily_pnl_pct) >= self.daily_loss_limit:
            self._pause(RiskViolation.DAILY_LOSS_LIMIT)
            return RiskValidationResult(False, RiskViolation.DAILY_LOSS_LIMIT,
                f"Pérdida diaria {self.daily_pnl_pct:.2f}%")

        if self.current_drawdown_pct >= self.drawdown_max_pct:
            self._pause(RiskViolation.DRAWDOWN_LIMIT)
            return RiskValidationResult(False, RiskViolation.DRAWDOWN_LIMIT,
                f"Drawdown {self.current_drawdown_pct:.2f}%")

        if self.consecutive_stops >= 3:
            self._pause(RiskViolation.CONSECUTIVE_STOPS)
            return RiskValidationResult(False, RiskViolation.CONSECUTIVE_STOPS,
                "3 stops consecutivos — pausa 24hs")

        logger.info(f"Señal aprobada | {signal.get('asset')} | SL:{stop_dist:.2f}% | R:R:{rr:.2f}")
        return RiskValidationResult(True, message="OK")

    def calc_position_size(self, capital: float, entry: float, stop_loss: float) -> dict:
        risk_usd     = capital * (self.risk_per_trade_pct / 100)
        stop_dist    = abs(entry - stop_loss)
        units        = risk_usd / stop_dist if stop_dist > 0 else 0
        position_pct = (units * entry / capital) * 100
        if position_pct > self.position_size_max:
            units        = (capital * self.position_size_max / 100) / entry
            position_pct = self.position_size_max
        return {"units": round(units,6), "risk_usd": round(risk_usd,2),
                "position_pct": round(position_pct,2), "r_value": round(risk_usd,2)}

    def register_result(self, result: str, pnl_pct: float):
        self.daily_pnl_pct += pnl_pct
        if result == "LOSS":
            self.consecutive_stops    += 1
            self.current_drawdown_pct += abs(pnl_pct) if pnl_pct < 0 else 0
        else:
            self.consecutive_stops     = 0
            self.current_drawdown_pct  = max(0, self.current_drawdown_pct - pnl_pct)
        logger.info(f"Resultado | {result} | P&L:{pnl_pct:+.2f}% | Diario:{self.daily_pnl_pct:+.2f}%")

    def kill_switch(self):
        self._pause(RiskViolation.DRAWDOWN_LIMIT)
        logger.warning("KILL SWITCH ACTIVADO")

    def resume(self):
        self.is_paused = False; self.pause_reason = None; self.consecutive_stops = 0
        logger.info("Agente reanudado")

    def reset_daily(self):
        self.daily_pnl_pct = 0.0
        if self.is_paused and self.pause_reason == RiskViolation.DAILY_LOSS_LIMIT:
            self.resume()

    def _pause(self, reason):
        self.is_paused = True; self.pause_reason = reason
        logger.warning(f"Agente pausado: {reason}")

    def _calc_rr(self, entry, stop, tp, direction):
        risk   = (entry - stop) if direction=="LONG" else (stop - entry)
        reward = (tp - entry)   if direction=="LONG" else (entry - tp)
        return round(reward/risk, 2) if risk > 0 else 0

    @property
    def status(self):
        return {"paused": self.is_paused, "daily_pnl_pct": self.daily_pnl_pct,
                "drawdown_pct": self.current_drawdown_pct, "consecutive_stops": self.consecutive_stops}
