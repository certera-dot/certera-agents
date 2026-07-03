"""
Supabase client — logging de trades, señales y eventos del agente.
Usa httpx directamente sobre la REST API de PostgREST para evitar conflictos
de versión del SDK supabase-py con httpx/python-telegram-bot.
Si las credenciales no están configuradas, opera en modo sin-DB.
"""
import os
import httpx
from loguru import logger


class SupabaseClient:
    def __init__(self):
        self.url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
        self.key = os.getenv("SUPABASE_SERVICE_KEY", "") or ""
        self._ok = bool(self.url and self.key and "your_" not in self.url)

        if not self._ok:
            logger.warning("Supabase: credenciales no configuradas — modo sin-DB")
        else:
            logger.info("Supabase OK (httpx directo)")

    def _headers(self) -> dict:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    async def _post(self, table: str, data: dict) -> dict | None:
        if not self._ok:
            return None
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{self.url}/rest/v1/{table}",
                    headers=self._headers(),
                    json=data,
                    timeout=10,
                )
                r.raise_for_status()
                rows = r.json()
                return rows[0] if isinstance(rows, list) and rows else rows
        except Exception as e:
            logger.error(f"Supabase POST {table}: {e}")
            return None

    async def _get(self, table: str, params: dict | None = None) -> list:
        if not self._ok:
            return []
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{self.url}/rest/v1/{table}",
                    headers=self._headers(),
                    params=params or {},
                    timeout=10,
                )
                r.raise_for_status()
                return r.json() or []
        except Exception as e:
            logger.error(f"Supabase GET {table}: {e}")
            return []

    async def _patch(self, table: str, params: dict, data: dict) -> dict | None:
        if not self._ok:
            return None
        try:
            async with httpx.AsyncClient() as client:
                r = await client.patch(
                    f"{self.url}/rest/v1/{table}",
                    headers=self._headers(),
                    params=params,
                    json=data,
                    timeout=10,
                )
                r.raise_for_status()
                rows = r.json()
                return rows[0] if isinstance(rows, list) and rows else rows
        except Exception as e:
            logger.error(f"Supabase PATCH {table}: {e}")
            return None

    async def log_trade(self, trade: dict) -> dict | None:
        return await self._post("trades", trade)

    async def log_signal(self, signal: dict) -> dict | None:
        return await self._post("signals", signal)

    async def log_event(self, event_type: str, data: dict) -> None:
        await self._post("agent_events", {"event_type": event_type, "data": data})

    async def get_recent_trades(self, limit: int = 50) -> list:
        return await self._get("trades", {
            "select": "*",
            "order": "created_at.desc",
            "limit": str(limit),
        })

    # ── Paper trading: ciclo abrir → monitorear → cerrar ────────────────

    async def get_open_trades(self) -> list:
        return await self._get("trades", {
            "select": "*",
            "result": "eq.OPEN",
            "order": "timestamp_open.asc",
        })

    async def update_trade(self, trade_id: str, updates: dict) -> dict | None:
        return await self._patch("trades", {"id": f"eq.{trade_id}"}, updates)

    async def count_closed_trades(self) -> int:
        """Cuenta trades ya cerrados (WIN/LOSS/BREAKEVEN) — usado para
        disparar update_pattern_weights cada N cierres."""
        if not self._ok:
            return 0
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{self.url}/rest/v1/trades",
                    headers={**self._headers(), "Prefer": "count=exact"},
                    params={"select": "id", "result": "in.(WIN,LOSS,BREAKEVEN)", "limit": "1"},
                    timeout=10,
                )
                cr = r.headers.get("content-range", "")  # formato "0-0/123"
                return int(cr.split("/")[-1]) if "/" in cr else 0
        except Exception as e:
            logger.error(f"Supabase count_closed_trades: {e}")
            return 0

    async def get_trades_by_methodology(self, methodology: str, limit: int = 500) -> list:
        """Trades cerrados de una metodología, más recientes primero —
        usado por update_pattern_weights para calcular win rate con decay."""
        return await self._get("trades", {
            "select": "*",
            "methodology": f"eq.{methodology}",
            "result": "in.(WIN,LOSS,BREAKEVEN)",
            "order": "timestamp_close.desc",
            "limit": str(limit),
        })

    # ── Pattern weights: pesos de confianza por metodología ─────────────

    async def get_pattern_weight(self, pattern_key: str) -> dict | None:
        rows = await self._get("pattern_weights", {
            "select": "*", "pattern_key": f"eq.{pattern_key}",
        })
        return rows[0] if rows else None

    async def upsert_pattern_weight(self, pattern: dict) -> dict | None:
        if not self._ok:
            return None
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{self.url}/rest/v1/pattern_weights",
                    headers={**self._headers(),
                             "Prefer": "resolution=merge-duplicates,return=representation"},
                    params={"on_conflict": "pattern_key"},
                    json=pattern,
                    timeout=10,
                )
                r.raise_for_status()
                rows = r.json()
                return rows[0] if isinstance(rows, list) and rows else rows
        except Exception as e:
            logger.error(f"Supabase UPSERT pattern_weights: {e}")
            return None
