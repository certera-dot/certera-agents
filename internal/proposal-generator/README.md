# Agente Generador de Propuestas — Certera

Genera borradores de propuestas comerciales personalizadas usando Claude a partir de datos del cliente en HubSpot.

## Flujo

1. Trigger: nuevo deal en HubSpot con stage "Propuesta"
2. Extrae datos del contacto y empresa
3. Claude genera propuesta usando template de `certera-templates`
4. Envía borrador a Notion para revisión del founder
5. Notifica por email cuando está lista

## Stack

- Claude API (claude-sonnet-4-6)
- HubSpot API
- Notion API
- n8n (orquestación)

## Variables de entorno

```
ANTHROPIC_API_KEY=
HUBSPOT_API_KEY=
NOTION_TOKEN=
NOTION_DATABASE_ID=
```
