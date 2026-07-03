"""
Binance connector — API pública para datos de mercado (siempre disponible),
testnet opcional para órdenes simuladas.
NUNCA ejecuta órdenes reales mientras SIMULATION_MODE=true.
"""
import os
import aiohttp
from loguru import logger

BINANCE_PUBLIC_URL = "https://api.binance.com"
BINANCE_TESTNET_URL = "https://testnet.binance.vision"


class BinanceConnector:
    def __init__(self):
        self.api_key    = os.getenv("BINANCE_API_KEY", "")
        self.secret     = os.getenv("BINANCE_SECRET_KEY", "")
        self.testnet    = os.getenv("BINANCE_TESTNET", "true").lower() == "true"
        self.simulation = os.getenv("SIMULATION_MODE", "true").lower() == "true"
        self.client     = None
        self._session   = None  # HTTP session para API pública (sin auth)

    async def connect(self) -> bool:
        # 1) Intentar conectar al exchange (testnet/live) para órdenes — opcional
        try:
            from binance import AsyncClient
            self.client = await AsyncClient.create(
                api_key=self.api_key,
                api_secret=self.secret,
                testnet=self.testnet,
            )
            info = await self.client.get_server_time()
            mode = "TESTNET" if self.testnet else "⚠️  LIVE"
            logger.info(f"Binance [{mode}] conectado | server_time={info['serverTime']}")
        except Exception as e:
            logger.warning(f"Binance exchange no disponible ({type(e).__name__}) — "
                           f"continuando con API pública para datos de mercado")
            self.client = None

        # 2) Siempre inicializar sesión HTTP para API pública (precios, velas)
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        try:
            async with self._session.get(f"{BINANCE_PUBLIC_URL}/api/v3/ping") as resp:
                if resp.status == 200:
                    logger.info("Binance [PUBLIC API] disponible — datos de mercado OK")
                    return True
                logger.error(f"Binance public API HTTP {resp.status}")
                return False
        except Exception as e:
            logger.error(f"Binance public API no alcanzable: {e}")
            return False

    def is_connected(self) -> bool:
        return self._session is not None and not self._session.closed

    async def get_price(self, symbol: str) -> float:
        """Precio en tiempo real desde la API pública (no requiere auth)."""
        async with self._session.get(
            f"{BINANCE_PUBLIC_URL}/api/v3/ticker/price",
            params={"symbol": symbol}
        ) as resp:
            data = await resp.json()
            return float(data["price"])

    async def get_klines(self, symbol: str, interval: str = "1h", limit: int = 100) -> list:
        """Velas desde la API pública."""
        try:
            async with self._session.get(
                f"{BINANCE_PUBLIC_URL}/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit}
            ) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"get_klines error: {e}")
            return []

    async def get_balance(self, asset: str = "USDT") -> float:
        if not self.client:
            logger.warning("get_balance: exchange autenticado no disponible")
            return 0.0
        try:
            acc = await self.client.get_asset_balance(asset=asset)
            return float(acc["free"]) if acc else 0.0
        except Exception as e:
            logger.error(f"Binance get_balance error: {e}")
            return 0.0

    async def place_order(self, symbol: str, side: str, quantity: float,
                          order_type: str = "MARKET") -> dict:
        if self.simulation:
            logger.warning(f"[SIMULACION] Orden {side} {quantity} {symbol} — no enviada")
            return {"simulated": True, "symbol": symbol, "side": side,
                    "quantity": quantity, "type": order_type}
        if not self.client:
            raise RuntimeError("Exchange autenticado no disponible — orden cancelada")
        try:
            order = await self.client.create_order(
                symbol=symbol, side=side, type=order_type, quantity=quantity
            )
            logger.info(f"Orden ejecutada: {order}")
            return order
        except Exception as e:
            logger.error(f"Binance place_order error: {e}")
            raise

    async def disconnect(self):
        if self.client:
            await self.client.close_connection()
            logger.info("Binance exchange desconectado")
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("Binance HTTP session cerrada")
