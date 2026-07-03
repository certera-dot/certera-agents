"""
Alpaca connector — datos y órdenes para NYSE/NASDAQ vía Alpaca Markets.
Paper trading por defecto (ALPACA_PAPER=true).
NUNCA ejecuta órdenes reales mientras SIMULATION_MODE=true.

Mercado abierto: lunes-viernes 09:30-16:00 ET (13:30-20:00 UTC).
"""
import os
from datetime import datetime, timezone
from loguru import logger

ALPACA_PAPER_URL = "https://paper-api.alpaca.markets"
ALPACA_LIVE_URL  = "https://api.alpaca.markets"
ALPACA_DATA_URL  = "https://data.alpaca.markets"

STOCK_WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY", "QQQ"]


def market_open() -> bool:
    """NYSE/NASDAQ: lunes-viernes 13:30-20:00 UTC."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 13 * 60 + 30 <= minutes < 20 * 60


class AlpacaConnector:
    def __init__(self):
        self.api_key    = os.getenv("ALPACA_API_KEY", "")
        self.api_secret = os.getenv("ALPACA_SECRET_KEY", "")
        self.paper      = os.getenv("ALPACA_PAPER", "true").lower() == "true"
        self.simulation = os.getenv("SIMULATION_MODE", "true").lower() == "true"
        self._session   = None
        self._base_url  = ALPACA_PAPER_URL if self.paper else ALPACA_LIVE_URL

    async def connect(self) -> bool:
        if not self.api_key or not self.api_secret:
            logger.warning("Alpaca: API keys no configuradas — conector desactivado")
            return False
        try:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={
                    "APCA-API-KEY-ID":     self.api_key,
                    "APCA-API-SECRET-KEY": self.api_secret,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            )
            async with self._session.get(f"{self._base_url}/v2/account") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    mode = "PAPER" if self.paper else "LIVE"
                    logger.info(f"Alpaca [{mode}] conectado | "
                                f"equity=${float(data.get('equity', 0)):,.2f}")
                    return True
                else:
                    body = await resp.text()
                    logger.error(f"Alpaca auth error HTTP {resp.status}: {body[:200]}")
                    return False
        except Exception as e:
            logger.warning(f"Alpaca connect error ({type(e).__name__}): {e} — desactivado")
            return False

    def is_connected(self) -> bool:
        return self._session is not None and not self._session.closed

    async def get_price(self, symbol: str) -> float:
        url = f"{ALPACA_DATA_URL}/v2/stocks/{symbol}/trades/latest"
        async with self._session.get(url) as resp:
            data = await resp.json()
            return float(data["trade"]["p"])

    async def get_klines(self, symbol: str, timeframe: str = "1Hour",
                         limit: int = 100) -> list:
        """Barras OHLCV normalizadas: [ts, open, high, low, close, volume]."""
        try:
            url = f"{ALPACA_DATA_URL}/v2/stocks/{symbol}/bars"
            params = {"timeframe": timeframe, "limit": limit, "adjustment": "raw"}
            async with self._session.get(url, params=params) as resp:
                data = await resp.json()
                bars = data.get("bars", [])
                return [[b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]] for b in bars]
        except Exception as e:
            logger.error(f"Alpaca get_klines {symbol}: {e}")
            return []

    async def place_order(self, symbol: str, side: str, qty: float,
                          order_type: str = "market") -> dict:
        if self.simulation:
            logger.warning(f"[SIMULACION] Alpaca {side} {qty} {symbol} — no enviada")
            return {"simulated": True, "symbol": symbol, "side": side,
                    "qty": qty, "type": order_type}
        if not market_open():
            raise RuntimeError(f"Mercado cerrado — orden {symbol} cancelada")
        try:
            payload = {"symbol": symbol, "qty": qty, "side": side,
                       "type": order_type, "time_in_force": "day"}
            async with self._session.post(
                f"{self._base_url}/v2/orders", json=payload
            ) as resp:
                order = await resp.json()
                logger.info(f"Alpaca orden ejecutada: {order}")
                return order
        except Exception as e:
            logger.error(f"Alpaca place_order error: {e}")
            raise

    @property
    def watchlist(self) -> list:
        return STOCK_WATCHLIST

    async def disconnect(self):
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("Alpaca session cerrada")
