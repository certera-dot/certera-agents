# Certera — Agents

Agentes IA y automatizaciones desarrollados por **Certera** para clientes y operación interna.

## Estructura

```
certera-agents/
├── internal/            # Agentes para operación interna de Certera
│   ├── pipeline-monitor/    # Monitoreo de pipeline de ventas
│   ├── proposal-generator/  # Generador de propuestas con IA
│   └── content-pipeline/    # Pipeline de contenido para LinkedIn
├── client-templates/    # Templates de agentes para clientes
│   ├── crm-agent/           # Agente de CRM y seguimiento de leads
│   ├── support-agent/       # Agente de soporte al cliente
│   └── data-analyst/        # Agente de análisis de datos
└── tools/               # Herramientas y utilities compartidas
```

## Stack

- **LLMs:** Claude (Anthropic) · GPT-4o
- **Frameworks:** LangChain · LangGraph · CrewAI
- **Automatización:** n8n
- **Backend:** Python (FastAPI) · Node.js
- **Vector DB:** Supabase pgvector · Pinecone
- **Observabilidad:** LangSmith · Helicone

## Principios de Desarrollo

Ver [CLAUDE.md en certera-core](https://github.com/certera-dot/certera-core/blob/main/CLAUDE.md#13-principios-de-desarrollo-de-software) para reglas completas.

---

**Cada agente en este repo debe tener:**
- README con descripción, arquitectura y variables de entorno
- `.env.example` con todas las variables necesarias (sin valores reales)
- Tests para lógica crítica
- Documentación de decisiones de diseño
