# TRADING AGENT — CLAUDE.md
## Agente de Trading Algorítmico Multi-Mercado con Aprendizaje Continuo

---

## IDENTIDAD DEL PROYECTO

Sistema de trading algorítmico con IA: monitoreo en tiempo real, detección de señales,
ejecución de órdenes y aprendizaje continuo basado en historial de operaciones.

Mercados: Binance (Spot + Futures) → Forex (CCXT/MetaTrader) → Alpaca (NYSE/NASDAQ) → ROFEX (Argentina)
Stack: Python + FastAPI + React + Supabase + pgvector + Telegram Bot API

---

## ARQUITECTURA

```
/trading-agent
├── core/           engine.py · risk_manager.py · signal_detector.py · learning_engine.py
├── connectors/     binance.py · forex.py · alpaca.py · rofex.py
├── rag/            embedder.py · retriever.py · /knowledge_base (PDFs)
├── execution/      order_manager.py · modes.py (MANUAL|SEMI|AUTO)
├── simulation/     paper_trading.py · backtester.py · scenario_generator.py
├── telegram/       bot.py
├── dashboard/      React frontend
├── database/       supabase.py · schema.sql
└── tests/          test_risk_manager.py (obligatorio antes de deploy)
```

---

## REGLA ABSOLUTA N°1 — RISK MANAGER

risk_manager.py NUNCA puede ser modificado por código automático.
TODA orden pasa por risk_manager.validate() antes de ejecutarse.
Si validate() retorna False → orden cancelada sin excepción.

Límites hardcodeados (solo editables en .env por el operador):
- stop_loss_max: 2% | position_size_max: 10% | drawdown_max: 15% | daily_loss: 5%

---

## REGLA ABSOLUTA N°2 — SIMULACIÓN PRIMERO

Orden de desarrollo y operación:
1. Backtest histórico (backtester.py)
2. Paper trading en tiempo real (paper_trading.py)
3. Capital real solo tras 500+ ops simuladas con win rate > 55% estable

SIMULATION_MODE=true en .env hasta que el operador lo cambie manualmente.

---

## MODOS DE OPERACIÓN

```python
class OperationMode(str, Enum):
    MANUAL    = "manual"   # Solo alertas — NUNCA ejecuta
    SEMI_AUTO = "semi"     # Propone + botones Telegram para confirmar
    AUTO      = "auto"     # Ejecuta dentro de parámetros de risk_manager
```

En simulación, el agente usa AUTO para maximizar volumen de aprendizaje.

---

## MÓDULO DE APRENDIZAJE (learning_engine.py)

Ciclo: pre_signal_filter() → operación → post_trade_analysis() →
       update_pattern_weights() → update_rag_context() → generate_insight()

Ventana temporal con decay exponencial:
- Últimas 50 ops: peso 1.0 | ops 51-200: peso 0.7 | 201-500: peso 0.4 | >500: peso 0.2

Anti-overfitting: mínimo 30 ops antes de ajustar pesos. Cambio máximo ±15% por ciclo.

---

## NIVELES DE MADUREZ DEL AGENTE

🟡 APRENDIZ      < 100 ops simuladas
🟠 EN FORMACIÓN   100-500 ops simuladas
🟢 CALIBRADO      500+ ops sim, win rate > 55% estable
🔵 PAPER READY    Inicia paper trading real
⭐ LIVE READY     200+ paper ops, resultados estables

Solo el operador promueve al siguiente nivel — el sistema recomienda, no decide.

---

## BASE DE CONOCIMIENTO RAG (dos capas)

Capa 1 — Cursos (estática): ICT · Wyckoff · Van Tharp · Stan Weinstein
Capa 2 — Experiencia propia (dinámica): generada por learning_engine cada 200 ops
La Capa 2 tiene PRIORIDAD sobre la Capa 1 en el retriever.

Formato de señal con aprendizaje integrado:
{asset, timeframe, signal_type, entry, stop_loss, take_profit[],
 confidence_raw, confidence_adjusted, methodology, historical_winrate,
 sample_size, risk_reward, pre_filter_passed, learning_context, mode, timestamp}

---

## REGLAS DE DESARROLLO

1. Tests primero: test_risk_manager.py debe pasar al 100% antes de cualquier deploy
2. Logging completo: toda señal y orden va a Supabase con timestamp
3. Nunca hardcodear API keys: usar .env
4. Manejo de errores: si una API falla → loggear + notificar Telegram + continuar sin esa API
5. Paper trading antes de live: ningún módulo de ejecución se activa sin validación previa
6. risk_manager.validate() es OBLIGATORIO antes de cualquier order_manager.execute()

---

## ORDEN DE DESARROLLO

Fase 1: risk_manager ✓ → binance WebSocket → signal_detector → learning_engine → backtester → telegram bot
Fase 2: embedder + RAG Capa 1 → retriever → paper_trading en tiempo real → scenario_generator
Fase 3: order_manager → modo SEMI_AUTO → dashboard React → modo AUTO
Fase 4: Forex (CCXT) → pares EURUSD·GBPUSD·USDJPY → señales adaptadas a sesiones forex
Fase 5: Alpaca (NYSE/NASDAQ) → ROFEX (Argentina) → fine-tuning (1000+ ops etiquetadas)
Fase 6: Multi-usuario → billing → comercialización

---

## VARIABLES DE ENTORNO REQUERIDAS

Ver .env.example en la raíz del proyecto.
NUNCA commitear .env — está en .gitignore.
