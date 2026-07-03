"""
Forex connector — datos de mercado vía yfinance (sin auth, sin restricciones geo).
Pares soportados: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD.

NUNCA ejecuta órdenes reales mientras SIMULATION_MODE=true.
Sesiones de mercado: Tokio 00-09 UTC | Londres 08-17 UTC | Nueva York 13-22 UTC.
"""
import asyncio
import os
from datetime import datetime, timezone
from loguru import logger


FOREX_PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD"]

# yfinance usa formato EURUSD=X
_YF_SYMBOL = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CAD": "USDCAD=X",
}

# Timeframe yfinance → intervalo
_TF_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1d",
}

# Sesiones Forex en UTC
SESSIONS = {
    "tokyo":    (0,  9),
    "london":   (8,  17),
    "new_york": (13, 22),
}


def current_session() -> str:
    """Retorna la sesión activa con mayor liquidez."""
    hour = datetime.now(timezone.utc).hour
    active = [s for s, (start, end) in SESSIONS.items() if start <= hour < end]
    if "london" in active and "new_york" in active:
        return "london+new_york"
    if active:
        return active[0]
    return "closed"


class ForexConnector:
    def __init__(self):
        self.simulation = os.getenv("SIMULATION_MODE", "true").lower() == "true"
        self._connected  = False
        self._pairs      = FOREX_PAIRS

    async def connect(self) -> bool:
        try:
            import yfinance as yf  # noqa: F401
            # Verificar con una descarga de prueba
            loop = asyncio.get_event_loop()
            ticker = await loop.run_in_executor(None, self._test_fetch)
            if ticker:
                self._connected = True
                logger.info(f"Forex [yfinance] conectado OK — pares: {self._pairs}")
                return True
            else:
                logger.warning("Forex [yfinance]: test fetch retornó vacío — desactivado")
                return False
        except ImportError:
            logger.warning("Forex: yfinance no instalado — conector desactivado")
            return False
        except Exception as e:
            logger.warning(f"Forex connect error ({type(e).__name__}): {e} — desactivado")
            return False

    def _test_fetch(self) -> bool:
        import yfinance as yf
        df = yf.download("EURUSD=X", period="1d", interval="1h", progress=False, auto_adjust=True)
        return not df.empty

    def is_connected(self) -> bool:
        return self._connected

    def is_market_open(self) -> bool:
        """Forex cierra viernes 22 UTC → lunes 00 UTC."""
        now = datetime.now(timezone.utc)
        if now.weekday() == 5:   # sábado
            return False
        if now.weekday() == 6:   # domingo antes de apertura Sydney
            return now.hour >= 22
        if now.weekday() == 4 and now.hour >= 22:  # viernes cierre
            return False
        return True

    async def get_klines(self, pair: str, timeframe: str = "1h", limit: int = 100) -> list:
        """Velas OHLCV. Formato compatible con Binance: [ts_ms, open, high, low, close, volume]."""
        try:
            yf_sym   = _YF_SYMBOL.get(pair, pair.replace("/", "") + "=X")
            interval = _TF_MAP.get(timeframe, "1h")
            # Período suficiente para cubrir 'limit' velas
            period_map = {"1m": "1d", "5m": "5d", "15m": "5d", "30m": "7d",
                          "1h": "7d", "4h": "30d", "1d": "90d"}
            period = period_map.get(interval, "7d")

            loop = asyncio.get_event_loop()
            rows = await loop.run_in_executor(
                None, self._fetch_ohlcv, yf_sym, interval, period
            )
            return rows[-limit:] if len(rows) > limit else rows
        except Exception as e:
            logger.error(f"Forex get_klines {pair}: {e}")
            return []

    def _fetch_ohlcv(self, symbol: str, interval: str, period: str) -> list:
        import yfinance as yf
        df = yf.download(symbol, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return []
        rows = []
        for ts, row in df.iterrows():
            ts_ms = int(ts.timestamp() * 1000)
            def _f(v):
                try:
                    return float(v.iloc[0]) if hasattr(v, "iloc") else float(v)
                except Exception:
                    return 0.0
            rows.append([
                ts_ms,
                _f(row["Open"]),
                _f(row["High"]),
                _f(row["Low"]),
                _f(row["Close"]),
                _f(row["Volume"]) if "Volume" in row else 0.0,
            ])
        return rows

    async def get_price(self, pair: str) -> float:
        rows = await self.get_klines(pair, timeframe="1m", limit=1)
        return rows[-1][4] if rows else 0.0  # close de la última vela

    async def get_spread(self, pair: str) -> float:
        """yfinance no provee spread real — retorna 0."""
        return 0.0

    async def place_order(self, pair: str, side: str, amount: float,
                          order_type: str = "market") -> dict:
        if self.simulation:
            logger.warning(f"[SIMULACION] Orden Forex {side} {amount} {pair} — no enviada")
            return {"simulated": True, "pair": pair, "side": side,
                    "amount": amount, "type": order_type,
                    "session": current_session()}
        raise RuntimeError("Forex live trading no implementado aún")

    @property
    def watchlist(self) -> list:
        return self._pairs

    async def disconnect(self):
        self._connected = False
        logger.info("Forex [yfinance] desconectado")
