"""
Signal Detector — detecta setups técnicos en klines de Binance.
Implementa: EMA crossover, RSI, estructura de precio básica.
Retorna señales compatibles con RiskManager.validate().
"""
import os
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class Signal:
    asset:        str
    signal_type:  str          # LONG | SHORT
    entry:        float
    stop_loss:    float
    take_profit:  list[float]
    timeframe:    str
    confidence:   float        # 0.0 – 1.0
    methodology:  str  = ""    # ema_cross | rsi_oversold | rsi_overbought | etc.
    indicators:   dict = field(default_factory=dict)
    min_rr:       float = 2.5

    def to_dict(self) -> dict:
        return {
            "asset":       self.asset,
            "signal_type": self.signal_type,
            "entry":       self.entry,
            "stop_loss":   self.stop_loss,
            "take_profit": self.take_profit,
            "timeframe":   self.timeframe,
            "confidence":  self.confidence,
            "methodology": self.methodology,
            "indicators":  self.indicators,
            "min_rr":      self.min_rr,
        }


class SignalDetector:
    WATCHLIST = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    FOREX_PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD"]

    ASSET_COOLDOWN_HOURS = 4  # no repetir el mismo activo por 4 horas

    def __init__(self):
        self.min_confidence = float(os.getenv("MIN_SIGNAL_CONFIDENCE", "0.72"))
        self._last_signal: dict = {}  # {asset: datetime}
        logger.info(f"SignalDetector OK | watchlist={self.WATCHLIST} | min_conf={self.min_confidence}")

    def detect(self, symbol: str, klines: list) -> Signal | None:
        """Analiza klines y retorna una señal si la hay, o None."""
        if len(klines) < 50:
            return None

        # ── Cooldown: ignorar activo si ya hubo señal reciente ───────────
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        last = self._last_signal.get(symbol)
        if last and (now - last) < timedelta(hours=self.ASSET_COOLDOWN_HOURS):
            remaining = int((timedelta(hours=self.ASSET_COOLDOWN_HOURS) - (now - last)).total_seconds() / 60)
            logger.debug(f"[COOLDOWN] {symbol} — próxima señal en {remaining} min")
            return None

        try:
            closes  = [float(k[4]) for k in klines]
            highs   = [float(k[2]) for k in klines]
            lows    = [float(k[3]) for k in klines]
            volumes = [float(k[5]) for k in klines]

            ema20 = self._ema(closes, 20)
            ema50 = self._ema(closes, 50)
            rsi   = self._rsi(closes, 14)
            atr   = self._atr(highs, lows, closes, 14)

            price     = closes[-1]
            prev_ema20 = ema20[-2]
            curr_ema20 = ema20[-1]
            curr_ema50 = ema50[-1]
            curr_rsi   = rsi[-1]
            curr_atr   = atr[-1]

            # volumen relativo al promedio de 20 períodos
            avg_vol = sum(volumes[-20:]) / 20
            vol_rel = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

            signal = None

            # Volumen confiable: avg_vol > 0 y no es datos dummy (forex yfinance = siempre 0)
            vol_reliable = avg_vol > 0.01
            vol_ok = (vol_rel > 1.1) if vol_reliable else True  # sin datos de vol, no filtrar

            # Ventana de cruce: busca en las últimas 3 velas (no solo la última)
            LOOKBACK = 3
            crossed_up   = any(
                ema20[-(i+2)] < ema50[-(i+2)] and ema20[-(i+1)] > ema50[-(i+1)]
                for i in range(LOOKBACK)
            )
            crossed_down = any(
                ema20[-(i+2)] > ema50[-(i+2)] and ema20[-(i+1)] < ema50[-(i+1)]
                for i in range(LOOKBACK)
            )

            # Log de diagnóstico cada scan
            logger.debug(
                f"[SCAN] {symbol} | ema20={round(curr_ema20,4)} ema50={round(curr_ema50,4)} "
                f"rsi={round(curr_rsi,1)} vol_rel={round(vol_rel,2)} vol_ok={vol_ok} "
                f"cross_up={crossed_up} cross_dn={crossed_down}"
            )

            # ── TIPO A: Cruce EMA + volumen confirmando ──────────────────────────────
            # stop=1.5×ATR, tp1=3.8×ATR → R:R=2.53 ✓ (antes 3.2 → 2.13)
            if crossed_up and curr_ema20 > curr_ema50 and curr_rsi < 65 and vol_ok:
                confidence = min(0.55 + (65 - curr_rsi) * 0.005, 1.0)
                if confidence >= self.min_confidence:
                    stop = price - 1.5 * curr_atr
                    tp1  = price + 3.8 * curr_atr
                    tp2  = price + 6.0 * curr_atr
                    signal = Signal(
                        asset=symbol, signal_type="LONG", entry=round(price, 6),
                        stop_loss=round(stop, 6), take_profit=[round(tp1, 6), round(tp2, 6)],
                        timeframe="1h", confidence=round(confidence, 2),
                        methodology="ema_cross", min_rr=2.5,
                        indicators={"ema20": round(curr_ema20, 4), "ema50": round(curr_ema50, 4),
                                    "rsi": round(curr_rsi, 2), "atr": round(curr_atr, 6),
                                    "vol_rel": round(vol_rel, 2), "setup": "ema_cross"},
                    )

            elif crossed_down and curr_ema20 < curr_ema50 and curr_rsi > 35 and vol_ok:
                confidence = min(0.55 + (curr_rsi - 35) * 0.005, 1.0)
                if confidence >= self.min_confidence:
                    stop = price + 1.5 * curr_atr
                    tp1  = price - 3.8 * curr_atr
                    tp2  = price - 6.0 * curr_atr
                    signal = Signal(
                        asset=symbol, signal_type="SHORT", entry=round(price, 6),
                        stop_loss=round(stop, 6), take_profit=[round(tp1, 6), round(tp2, 6)],
                        timeframe="1h", confidence=round(confidence, 2),
                        methodology="ema_cross", min_rr=2.5,
                        indicators={"ema20": round(curr_ema20, 4), "ema50": round(curr_ema50, 4),
                                    "rsi": round(curr_rsi, 2), "atr": round(curr_atr, 6),
                                    "vol_rel": round(vol_rel, 2), "setup": "ema_cross"},
                    )

            # ── TIPO B: RSI extremo — umbral más estricto (25/75 en vez de 28/72) ───
            # stop=2×ATR, tp1=5.0×ATR → R:R=2.5 ✓ (antes 4.2 → 2.1)
            if signal is None:
                # Sobreventa extrema RSI < 25
                if curr_rsi < 25:
                    confidence = min(0.60 + (25 - curr_rsi) * 0.015, 1.0)
                    if confidence >= self.min_confidence:
                        stop = price - 2.0 * curr_atr
                        tp1  = price + 5.0 * curr_atr
                        tp2  = price + 7.5 * curr_atr
                        signal = Signal(
                            asset=symbol, signal_type="LONG", entry=round(price, 6),
                            stop_loss=round(stop, 6), take_profit=[round(tp1, 6), round(tp2, 6)],
                            timeframe="1h", confidence=round(confidence, 2),
                            methodology="rsi_oversold", min_rr=2.5,
                            indicators={"ema20": round(curr_ema20, 4), "ema50": round(curr_ema50, 4),
                                        "rsi": round(curr_rsi, 2), "atr": round(curr_atr, 6),
                                        "vol_rel": round(vol_rel, 2), "setup": "rsi_oversold"},
                        )

                # Sobrecompra extrema RSI > 75
                elif curr_rsi > 75:
                    confidence = min(0.60 + (curr_rsi - 75) * 0.015, 1.0)
                    if confidence >= self.min_confidence:
                        stop = price + 2.0 * curr_atr
                        tp1  = price - 5.0 * curr_atr
                        tp2  = price - 7.5 * curr_atr
                        signal = Signal(
                            asset=symbol, signal_type="SHORT", entry=round(price, 6),
                            stop_loss=round(stop, 6), take_profit=[round(tp1, 6), round(tp2, 6)],
                            timeframe="1h", confidence=round(confidence, 2),
                            methodology="rsi_overbought", min_rr=2.5,
                            indicators={"ema20": round(curr_ema20, 4), "ema50": round(curr_ema50, 4),
                                        "rsi": round(curr_rsi, 2), "atr": round(curr_atr, 6),
                                        "vol_rel": round(vol_rel, 2), "setup": "rsi_overbought"},
                        )

            if signal:
                self._last_signal[symbol] = now  # registrar cooldown
                logger.info(f"Señal detectada | {signal.asset} {signal.signal_type} "
                            f"entry={signal.entry} conf={signal.confidence} "
                            f"setup={signal.indicators.get('setup','?')} "
                            f"[cooldown 4h activo]")
            return signal

        except Exception as e:
            logger.error(f"SignalDetector error en {symbol}: {e}")
            return None

    # ── Cálculos técnicos ────────────────────────────────────────────────

    @staticmethod
    def _ema(data: list, period: int) -> list:
        k = 2 / (period + 1)
        ema = [data[0]]
        for v in data[1:]:
            ema.append(v * k + ema[-1] * (1 - k))
        return ema

    @staticmethod
    def _rsi(closes: list, period: int = 14) -> list:
        rsi = [50.0] * period
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
            if i >= period:
                avg_g = sum(gains[-period:]) / period
                avg_l = sum(losses[-period:]) / period
                if avg_l == 0:
                    rsi.append(100.0)
                else:
                    rs = avg_g / avg_l
                    rsi.append(100 - 100 / (1 + rs))
        return rsi

    @staticmethod
    def _atr(highs: list, lows: list, closes: list, period: int = 14) -> list:
        trs = []
        for i in range(1, len(closes)):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
            trs.append(tr)
        if not trs:
            return [0.0] * len(closes)
        atr = [sum(trs[:period]) / period]
        for tr in trs[period:]:
            atr.append((atr[-1] * (period - 1) + tr) / period)
        padding = len(closes) - len(atr)
        return [atr[0]] * padding + atr
