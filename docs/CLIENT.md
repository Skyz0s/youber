# Cliente MCP — BARF

Guía del cliente MCP: conecta agentes de IA y terminales al servidor del
framework (`youber/mcp/server.py`) usando el **MCP Python SDK 2.x**.

## Instalación

```bash
pip install -e ".[dev]"
playwright install chromium
```

## Uso rápido

### Desde código

```python
import asyncio
from youber.client.session import create_mcp_session
from youber.client.tools import MCPTools

async def main():
    async with create_mcp_session() as session:   # stdio por defecto
        tools = MCPTools(session)

        info = await tools.open_page("https://example.com")
        print(info["title"], info["status"])

        audit = await tools.audit_accessibility("https://example.com")
        print(f"Violaciones: {audit['total_violations']}")

        signals = await tools.simulate_geolocation("https://example.com", "JP")
        print(signals["navigator_language"], signals["timezone"])

asyncio.run(main())
```

### CLI interactiva

```bash
youber-client
```

```
⚙️ Youber — BARF. Escribe 'help' para los comandos.
youber> audit https://example.com
youber> geo JP https://example.com
youber> journey https://example.com https://example.org
youber> exit
```

Comandos: `open`, `audit`, `journey`, `geo`, `network`, `device`, `help`,
`exit`.

## Transportes

`create_mcp_session(transport=...)` soporta:

| Transporte | Cuándo usarlo | Parámetros |
|---|---|---|
| `stdio` (por defecto) | Servidor local, desarrollo | `command`, `server_args` |
| `sse` | Servidor remoto (SSE) | `url` |
| `streamable-http` | Servidor remoto (HTTP moderno) | `url` |

Ejemplo remoto:

```python
async with create_mcp_session(transport="sse", url="http://127.0.0.1:8000/sse") as session:
    ...
```

La sesión se inicializa con reintentos (`retries=3` por defecto) y espera
progresiva; todas las operaciones se registran con loguru.

## Métodos de `MCPTools`

| Método | Herramienta MCP | Descripción |
|---|---|---|
| `open_page(url)` | `open_page` | Abre una página |
| `audit_accessibility(url)` | `open_page` + `audit_accessibility` | Auditoría axe-core |
| `trace_journey(urls)` | `open_page` + `navigate_to` | Recorrido con la misma página |
| `simulate_geolocation(url, region)` | `simulate_geolocation` | Señales de localización |
| `simulate_network(url, speed)` | `simulate_network` | Perfil de red |
| `simulate_device(url, device)` | `simulate_device` | Dispositivo emulado |
| `get_help()` | — | Ayuda del cliente |

Las respuestas se devuelven como dicts JSON (parseadas de
`CallToolResult`). Si la herramienta devuelve un error, se lanza
`RuntimeError` con el detalle.

## Arquitectura

```
src/youber/client/
├── session.py      create_mcp_session (stdio/sse/streamable-http + reintentos)
├── tools.py        MCPTools (wrappers tipados + parseo de respuestas)
└── interactive.py  CLI interactiva (rich) + execute_command testeable
```
