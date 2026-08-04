"""
Tech Lead Agent — capa de decisión contextual entre detección de señal y ejecución.

FASE 1 (activa): shadow mode — evalúa cada señal con contexto histórico y decide
(EXECUTE / REDUCE_SIZE / PAUSE), pero NO bloquea al risk manager. Loggea en
Supabase y adjunta su veredicto al mensaje de Telegram para que el operador
pueda comparar y validar antes de darle control real.

FASE 2: reemplaza la lógica de auto-pause duro del risk manager en SEMI_AUTO.
"""
import json
import os
from loguru import logger

EXECUTE      = "EXECUTE"
REDUCE_SIZE  = "REDUCE_SIZE"
PAUSE        = "PAUSE"


class TechLeadAgent:
    SHADOW_MODE = True

    def __init__(self, db):
        self.db     = db
        self.client = None
        self.model  = "claude-haiku-4-5-20251001"

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key or "your_" in api_key:
            logger.warning("TechLeadAgent: ANTHROPIC_API_KEY no configurada — modo offline")
            return
        try:
            from anthropic import AsyncAnthropic
            self.client = AsyncAnthropic(api_key=api_key)
            logger.info("TechLeadAgent OK | shadow mode activo")
        except Exception as e:
            logger.warning(f"TechLeadAgent: error init ({e})")

    async def evaluate(self, signal: dict, consecutive_losses: int,
                       recent_trades: list) -> dict:
        """
        Evalúa una señal con contexto histórico del setup.
        Retorna siempre un dict con decision/justification/confidence.
        En shadow mode nunca bloquea la ejecución — solo informa.
        """
        setup = signal.get("methodology", "unknown")
        asset = signal.get("asset", "?")

        setup_trades = [t for t in recent_trades if t.get("methodology") == setup]
        wins  = sum(1 for t in setup_trades if t.get("result") == "WIN")
        total = len(setup_trades)
        wr    = (wins / total * 100) if total > 0 else None

        atr        = signal.get("indicators", {}).get("atr", 0)
        precedents = await self.db.get_decision_log(setup, limit=5)

        decision, justification, confidence = await self._decide(
            setup=setup, asset=asset,
            consecutive_losses=consecutive_losses,
            atr=atr, win_rate=wr, sample_size=total,
            precedents=precedents,
        )

        await self.db.log_decision({
            "setup":    setup,
            "asset":    asset,
            "signal_context": {
                "entry":              signal.get("entry"),
                "stop_loss":          signal.get("stop_loss"),
                "atr":                atr,
                "consecutive_losses": consecutive_losses,
                "win_rate":           wr,
                "sample_size":        total,
            },
            "decision":      decision,
            "justification": justification,
            "confidence":    confidence,
            "shadow_mode":   self.SHADOW_MODE,
        })

        logger.info(
            f"TechLead [SHADOW] {asset} {setup} | "
            f"losses={consecutive_losses} wr={f'{wr:.0f}%' if wr is not None else 'n/a'} "
            f"→ {decision} ({confidence:.0%})"
        )
        return {
            "decision":           decision,
            "justification":      justification,
            "confidence":         confidence,
            "consecutive_losses": consecutive_losses,
        }

    async def _decide(self, setup: str, asset: str, consecutive_losses: int,
                      atr: float, win_rate, sample_size: int,
                      precedents: list) -> tuple:
        if not self.client:
            return self._rule_fallback(consecutive_losses, win_rate)

        prec_text = ""
        if precedents:
            lines = []
            for p in precedents:
                ctx = p.get("signal_context") or {}
                outcome = p.get("outcome") or "pendiente"
                lines.append(
                    f"  • {str(p.get('timestamp',''))[:10]}: losses={ctx.get('consecutive_losses','?')} "
                    f"→ {p.get('decision')} | resultado: {outcome}"
                )
            prec_text = "\nPrecedentes de este setup:\n" + "\n".join(lines)

        wr_text = f"{win_rate:.0f}% (n={sample_size})" if win_rate is not None else "sin datos suficientes"

        prompt = (
            f"Setup: {setup} | Activo: {asset}\n"
            f"Pérdidas consecutivas: {consecutive_losses}\n"
            f"ATR actual: {round(atr, 6)}\n"
            f"Win rate reciente: {wr_text}"
            f"{prec_text}\n\n"
            f"¿Qué hacer con la próxima señal de este setup?\n"
            f"Opciones: EXECUTE, REDUCE_SIZE (mitad del tamaño), PAUSE\n"
            f'Responde SOLO JSON: {{"decision":"EXECUTE|REDUCE_SIZE|PAUSE","justification":"...","confidence":0.0}}'
        )
        try:
            msg = await self.client.messages.create(
                model=self.model, max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text  = msg.content[0].text.strip()
            start = text.find("{")
            end   = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                dec  = data.get("decision", EXECUTE).upper()
                if dec not in (EXECUTE, REDUCE_SIZE, PAUSE):
                    dec = EXECUTE
                return dec, data.get("justification", ""), float(data.get("confidence", 0.7))
        except Exception as e:
            logger.error(f"TechLeadAgent._decide: {e}")

        return self._rule_fallback(consecutive_losses, win_rate)

    @staticmethod
    def _rule_fallback(consecutive_losses: int, win_rate) -> tuple:
        if consecutive_losses >= 4:
            return PAUSE, "4+ pérdidas consecutivas — pausa preventiva (fallback)", 0.6
        if consecutive_losses >= 2:
            return REDUCE_SIZE, "2+ pérdidas consecutivas — reducir tamaño (fallback)", 0.55
        return EXECUTE, "Sin señales de advertencia", 0.8
