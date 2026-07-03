"""
Learning Engine — analiza patrones de trades pasados y provee contexto de mercado
usando Claude como motor de razonamiento. Opera en modo offline si no hay API key.
"""
import os
import json
from loguru import logger


class LearningEngine:
    # Metodologías que produce signal_detector.py — deben coincidir 1:1
    METHODOLOGIES = ["ema_cross", "rsi_oversold", "rsi_overbought"]

    # Anti-overfitting (ver CLAUDE.md): sin esto el agente reaccionaría
    # a rachas cortas en vez de patrones reales.
    MIN_TRADES_FOR_ADJUSTMENT  = 30
    MAX_WEIGHT_CHANGE_PER_CYCLE = 0.15

    def __init__(self, db):
        self.db         = db
        self.client     = None
        self.model      = "claude-haiku-4-5-20251001"  # rápido y económico para análisis rutinario
        self._trade_log = []

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key or "your_" in api_key:
            logger.warning("LearningEngine: ANTHROPIC_API_KEY no configurada — modo offline")
            return

        try:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=api_key)
            logger.info("LearningEngine OK (Claude activo)")
        except ImportError:
            logger.warning("LearningEngine: paquete anthropic no instalado")
        except Exception as e:
            logger.warning(f"LearningEngine: error al inicializar Anthropic ({e}) — modo offline")

    async def analyze_signal(self, signal: dict, recent_trades: list | None = None) -> str:
        """Pide a Claude una evaluación breve de la señal en contexto."""
        if not self.client:
            return "Análisis offline — Claude no disponible."

        trades_summary = ""
        if recent_trades:
            wins  = sum(1 for t in recent_trades if t.get("result") == "WIN")
            total = len(recent_trades)
            trades_summary = f"\nÚltimos {total} trades: {wins} wins ({wins/total*100:.0f}% WR)."

        prompt = (
            f"Señal de trading recibida:\n{json.dumps(signal, indent=2)}"
            f"{trades_summary}\n\n"
            f"Evalúa brevemente (3 líneas máx): "
            f"¿La señal tiene sentido técnico? ¿Qué riesgos ves?"
        )
        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
        except Exception as e:
            logger.error(f"LearningEngine analyze_signal: {e}")
            return f"Error en análisis: {e}"

    async def learn_from_trade(self, trade: dict) -> None:
        """Incorpora un trade ya cerrado al contexto de aprendizaje en memoria.
        El trade ya fue persistido en Supabase por PaperTradingManager —
        no se vuelve a insertar acá (antes esto duplicaba la fila)."""
        self._trade_log.append(trade)
        if len(self._trade_log) > 200:
            self._trade_log = self._trade_log[-200:]
        logger.info(f"Trade incorporado al aprendizaje | {trade.get('asset')} {trade.get('result')} "
                    f"{trade.get('pnl_pct', 0):+.2f}%")

    async def get_weight_factor(self, methodology: str | None) -> float:
        """Peso de confianza aprendido para una metodología (1.0 = neutro,
        sin historial suficiente todavía). Se aplica sobre confidence_raw
        para obtener confidence_adjusted en cada señal nueva."""
        if not methodology:
            return 1.0
        pattern = await self.db.get_pattern_weight(methodology)
        return float(pattern["weight_factor"]) if pattern else 1.0

    async def update_pattern_weights(self) -> dict:
        """Recalcula el weight_factor de cada metodología a partir de los
        trades cerrados, con decay exponencial por antigüedad (ver CLAUDE.md):
        últimas 50 ops peso 1.0 | 51-200 peso 0.7 | 201-500 peso 0.4 | >500 peso 0.2.
        Anti-overfitting: mínimo 30 ops y cambio máximo ±15% por ciclo.
        Retorna un resumen {metodología: {win_rate, weight, sample_size}}."""
        summary = {}
        for methodology in self.METHODOLOGIES:
            trades = await self.db.get_trades_by_methodology(methodology, limit=500)
            if len(trades) < self.MIN_TRADES_FOR_ADJUSTMENT:
                logger.debug(f"update_pattern_weights: {methodology} tiene {len(trades)} trades "
                             f"(< {self.MIN_TRADES_FOR_ADJUSTMENT} mínimo) — sin ajuste todavía")
                continue

            # trades viene ordenado por timestamp_close DESC (más reciente primero)
            weighted_wins = weighted_total = 0.0
            winner_pnls, loser_pnls = [], []
            for i, t in enumerate(trades):
                if   i < 50:  decay = 1.0
                elif i < 200: decay = 0.7
                elif i < 500: decay = 0.4
                else:         decay = 0.2

                weighted_total += decay
                if t.get("result") == "WIN":
                    weighted_wins += decay
                    winner_pnls.append(float(t.get("pnl_pct") or 0))
                elif t.get("result") == "LOSS":
                    loser_pnls.append(float(t.get("pnl_pct") or 0))

            win_rate   = (weighted_wins / weighted_total) if weighted_total > 0 else 0
            avg_winner = sum(winner_pnls) / len(winner_pnls) if winner_pnls else 0
            avg_loser  = sum(loser_pnls)  / len(loser_pnls)  if loser_pnls  else 0
            expectancy = (win_rate * avg_winner) + ((1 - win_rate) * avg_loser)

            # weight_factor neutro=1.0. WR=70% -> ~1.2 (más confianza) | WR=40% -> ~0.9
            target_weight = max(0.3, min(1.5, 0.5 + win_rate))

            previous    = await self.db.get_pattern_weight(methodology)
            prev_weight = float(previous["weight_factor"]) if previous else 1.0

            delta        = target_weight - prev_weight
            capped_delta = max(-self.MAX_WEIGHT_CHANGE_PER_CYCLE,
                                min(self.MAX_WEIGHT_CHANGE_PER_CYCLE, delta))
            new_weight   = round(prev_weight + capped_delta, 3)

            wins   = sum(1 for t in trades if t.get("result") == "WIN")
            losses = sum(1 for t in trades if t.get("result") == "LOSS")

            await self.db.upsert_pattern_weight({
                "pattern_key":   methodology,
                "methodology":   methodology,
                "win_count":     wins,
                "loss_count":    losses,
                "total_count":   len(trades),
                "win_rate":      round(win_rate * 100, 2),
                "avg_winner_r":  round(avg_winner, 2),
                "avg_loser_r":   round(avg_loser, 2),
                "expectancy":    round(expectancy, 2),
                "weight_factor": new_weight,
            })

            summary[methodology] = {
                "win_rate": round(win_rate * 100, 1),
                "weight":   new_weight,
                "sample_size": len(trades),
            }
            logger.info(f"Pattern weight actualizado | {methodology} | "
                        f"WR={win_rate*100:.1f}% peso={new_weight} (prev={prev_weight}) n={len(trades)}")

        return summary

    async def get_performance_summary(self) -> str:
        """Resumen de rendimiento con análisis de Claude."""
        trades = await self.db.get_recent_trades(50) or self._trade_log[-50:]
        if not trades:
            return "Sin historial de trades todavía."

        wins     = sum(1 for t in trades if t.get("result") == "WIN")
        losses   = len(trades) - wins
        pnl_list = [t.get("pnl_pct", 0) for t in trades]
        avg_pnl  = sum(pnl_list) / len(pnl_list) if pnl_list else 0

        summary = (f"Últimos {len(trades)} trades: {wins}W/{losses}L | "
                   f"Win rate: {wins/len(trades)*100:.1f}% | Avg P&L: {avg_pnl:+.2f}%")

        if self.client and len(trades) >= 5:
            prompt = (f"Datos de trading: {summary}\n"
                      f"Dame en 2 líneas el patrón más relevante y qué ajustar.")
            try:
                msg = self.client.messages.create(
                    model=self.model, max_tokens=150,
                    messages=[{"role": "user", "content": prompt}],
                )
                return f"{summary}\n\n🤖 {msg.content[0].text}"
            except Exception:
                pass

        return summary
