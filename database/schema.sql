-- ─────────────────────────────────────────────────────────────
--  TRADING AGENT — Esquema Supabase
--  Ejecutar en Supabase SQL Editor antes de iniciar el agente
-- ─────────────────────────────────────────────────────────────

-- ── Habilitar extensión vector para RAG ──────────────────────
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Operaciones (historial completo) ─────────────────────────
CREATE TABLE IF NOT EXISTS trades (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mode                TEXT NOT NULL CHECK (mode IN ('simulation','paper','live')),
  asset               TEXT NOT NULL,
  timeframe           TEXT NOT NULL,
  session             TEXT,
  day_of_week         TEXT,
  methodology         TEXT,
  secondary_confluence TEXT[],
  entry               DECIMAL(20,8),
  stop_loss           DECIMAL(20,8),
  take_profit         DECIMAL(20,8)[],
  exit_price          DECIMAL(20,8),
  exit_reason         TEXT,
  result              TEXT CHECK (result IN ('WIN','LOSS','BREAKEVEN','OPEN')),
  pnl_pct             DECIMAL(10,4),
  pnl_usd             DECIMAL(10,2),
  duration_minutes    INTEGER,
  agent_confidence    DECIMAL(4,2),
  confidence_adjusted DECIMAL(4,2),
  risk_reward         DECIMAL(6,2),
  market_context      JSONB,
  learning_notes      TEXT,
  timestamp_open      TIMESTAMPTZ DEFAULT NOW(),
  timestamp_close     TIMESTAMPTZ,
  created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── Señales detectadas (todas, ejecutadas o no) ───────────────
CREATE TABLE IF NOT EXISTS signals (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trade_id            UUID REFERENCES trades(id),
  asset               TEXT NOT NULL,
  timeframe           TEXT NOT NULL,
  signal_type         TEXT CHECK (signal_type IN ('LONG','SHORT')),
  entry               DECIMAL(20,8),
  stop_loss           DECIMAL(20,8),
  take_profit         DECIMAL(20,8)[],
  confidence_raw      DECIMAL(4,2),
  confidence_adjusted DECIMAL(4,2),
  methodology         TEXT,
  rag_context         TEXT,
  pre_filter_passed   BOOLEAN DEFAULT FALSE,
  historical_winrate  DECIMAL(4,2),
  sample_size         INTEGER DEFAULT 0,
  risk_reward         DECIMAL(6,2),
  was_executed        BOOLEAN DEFAULT FALSE,
  execution_mode      TEXT,
  market_context      JSONB,
  timestamp           TIMESTAMPTZ DEFAULT NOW()
);

-- ── Métricas de aprendizaje por patrón ───────────────────────
CREATE TABLE IF NOT EXISTS pattern_weights (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pattern_key         TEXT UNIQUE NOT NULL,
  methodology         TEXT,
  asset               TEXT,
  timeframe           TEXT,
  session             TEXT,
  day_of_week         TEXT,
  win_count           INTEGER DEFAULT 0,
  loss_count          INTEGER DEFAULT 0,
  total_count         INTEGER DEFAULT 0,
  win_rate            DECIMAL(4,2) DEFAULT 0,
  avg_winner_r        DECIMAL(6,2) DEFAULT 0,
  avg_loser_r         DECIMAL(6,2) DEFAULT 0,
  expectancy          DECIMAL(6,2) DEFAULT 0,
  weight_factor       DECIMAL(4,2) DEFAULT 1.0,
  last_updated        TIMESTAMPTZ DEFAULT NOW()
);

-- ── Documentos RAG (base de conocimiento vectorial) ───────────
CREATE TABLE IF NOT EXISTS rag_documents (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title       TEXT NOT NULL,
  source      TEXT,
  layer       TEXT CHECK (layer IN ('courses','experience')),
  content     TEXT NOT NULL,
  embedding   vector(1536),
  metadata    JSONB,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── Estado del agente ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_state (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  operation_mode      TEXT DEFAULT 'manual',
  simulation_mode     BOOLEAN DEFAULT TRUE,
  maturity_level      TEXT DEFAULT 'aprendiz',
  is_paused           BOOLEAN DEFAULT FALSE,
  pause_reason        TEXT,
  daily_pnl_pct       DECIMAL(8,4) DEFAULT 0,
  drawdown_pct        DECIMAL(8,4) DEFAULT 0,
  consecutive_stops   INTEGER DEFAULT 0,
  total_trades        INTEGER DEFAULT 0,
  win_rate_global     DECIMAL(4,2) DEFAULT 0,
  expectancy_global   DECIMAL(6,2) DEFAULT 0,
  updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── Eventos del agente (logs estructurados) ─────────────────
CREATE TABLE IF NOT EXISTS agent_events (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type  TEXT NOT NULL,
  data        JSONB,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── Índices ───────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_trades_asset         ON trades(asset);
CREATE INDEX IF NOT EXISTS idx_trades_methodology   ON trades(methodology);
CREATE INDEX IF NOT EXISTS idx_trades_result        ON trades(result);
CREATE INDEX IF NOT EXISTS idx_trades_mode          ON trades(mode);
CREATE INDEX IF NOT EXISTS idx_signals_asset        ON signals(asset);
CREATE INDEX IF NOT EXISTS idx_pattern_key          ON pattern_weights(pattern_key);

-- Índice vectorial para RAG
CREATE INDEX IF NOT EXISTS idx_rag_embedding
  ON rag_documents USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- ── Función: buscar documentos similares ──────────────────────
CREATE OR REPLACE FUNCTION match_documents(
  query_embedding vector(1536),
  match_threshold FLOAT DEFAULT 0.7,
  match_count     INT   DEFAULT 5
)
RETURNS TABLE (
  id         UUID,
  title      TEXT,
  content    TEXT,
  layer      TEXT,
  similarity FLOAT
)
LANGUAGE SQL STABLE AS $$
  SELECT id, title, content, layer,
         1 - (embedding <=> query_embedding) AS similarity
  FROM   rag_documents
  WHERE  1 - (embedding <=> query_embedding) > match_threshold
  ORDER  BY embedding <=> query_embedding
  LIMIT  match_count;
$$;
