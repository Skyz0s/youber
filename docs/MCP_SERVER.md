# Servidor MCP — BARF

El servidor MCP (Model Context Protocol) expone las funcionalidades del
framework como **herramientas** que agentes de IA pueden invocar de forma
estándar. Está implementado con el **MCP Python SDK 2.x** (clase
`MCPServer`, antigua `FastMCP`) y soporta transporte **stdio** (por
defecto), **SSE** y **streamable-http**.

## Herramientas

| Herramienta | Parámetros | Descripción |
|---|---|---|
| `open_page` | `url: str`, `page_id: str \| None = None` | Abre una página (nueva o reutilizando `page_id`) y devuelve su información |
| `navigate_to` | `url: str`, `page_id: str` | Navega una página existente a una nueva URL |
| `get_page_info` | `page_id: str` | URL, título y viewport de una página de la sesión |
| `audit_accessibility` | `page_id: str` | Auditoría de accesibilidad con axe-core sobre una página |
| `simulate_geolocation` | `url: str`, `region: str` | Abre la URL con geo/idioma/zona horaria de la región y devuelve las señales detectadas |
| `simulate_network` | `url: str`, `speed: str` | Abre la URL con un perfil de red (4g, 3g, 2g, slow-3g, offline) |
| `simulate_device` | `url: str`, `device_name: str` | Abre la URL con un dispositivo (iPhone, Pixel, iPad, Desktop) |

> **Sesiones:** el servidor mantiene un navegador compartido. Cada página
> abierta recibe un `page_id` (UUID corto) y persiste entre llamadas, de modo
> que un agente puede abrir → inspeccionar → navegar → auditar.

## Formato de respuestas

### `open_page(url, page_id?)`

```json
{
  "page_id": "3f2a9c1d",
  "url": "https://example.com",
  "title": "Example Domain",
  "status": 200,
  "logs": ["10:31:02 | INFO     | Lanzando navegador...", "..."]
}
```

- `status` es `null` para esquemas sin respuesta HTTP (`file://`, `data:`).
- `logs` contiene los mensajes del proceso (útil para depuración y educación).

### `navigate_to(url, page_id)`

```json
{
  "previous_url": "file:///.../accessible.html",
  "new_url": "https://example.com",
  "status": 200
}
```

### `get_page_info(page_id)`

```json
{
  "url": "https://example.com",
  "title": "Example Domain",
  "viewport": { "width": 1920, "height": 1080 }
}
```

### `audit_accessibility(page_id)`

```json
{
  "violations": [],
  "passes": [ { "id": "color-contrast", "impact": "serious", "...": "..." } ],
  "incomplete": [],
  "total_violations": 0,
  "message": "✅ Sin violaciones de accesibilidad detectadas."
}
```

- Con violaciones, `message` es `null` y `violations` contiene los detalles
  de cada regla incumplida (id, impacto, descripción, nodos afectados).

## Códigos de error

Las excepciones del núcleo se propagan como errores de herramienta MCP con
mensajes descriptivos:

| Excepción | Cuándo | Mensaje típico |
|---|---|---|
| `TimeoutException` | La operación supera el timeout | `Timeout (30000 ms) navegando a <url>` |
| `NavigationException` | Fallo al navegar | `No se pudo navegar a <url>: <detalle>` |
| `BrowserException` | Error general (página inexistente, navegador sin lanzar) | `Página no encontrada en la sesión: <page_id>` |

## Uso

### 1. Stdio (por defecto)

```bash
python -m youber.mcp.server
```

Conecta un cliente MCP (Claude, claude-code, etc.) apuntando al comando:

```bash
claude mcp add barf -- python -m youber.mcp.server
```

### 2. SSE / Streamable HTTP

```bash
python -m youber.mcp.server --transport sse --host 127.0.0.1 --port 8000
python -m youber.mcp.server --transport streamable-http --port 8000
```

### 3. Cliente Python (ejemplo educativo)

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command="python", args=["-m", "youber.mcp.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([t.name for t in tools.tools])

            result = await session.call_tool(
                "open_page", {"url": "https://example.com"}
            )
            print(result.content)

asyncio.run(main())
```

## Nota sobre la migración a MCP 2.x

- `FastMCP` (mcp<2) se renombró a `MCPServer` (import:
  `from mcp.server.mcpserver import MCPServer`).
- Los campos de los tipos de protocolo pasaron de camelCase a snake_case
  (p. ej. `Tool.input_schema`).
- `McpError` pasó a llamarse `MCPError`.
- Las herramientas del servidor devuelven dicts JSON-serializables
  (`model_dump()`) para máxima compatibilidad con el protocolo 2.x.
- Guía oficial: <https://py.sdk.modelcontextprotocol.io/v2/migration/>.

## Nota sobre axe-core

La auditoría de accesibilidad usa **axe-core embebido** en
`src/youber/assets/axe.min.js` (distribución oficial de axe-core v4.10.2).
Se distribuye *vendored* para que las auditorías sean deterministas y
funcionen sin red. La implementación vive en `youber/accessibility/axe_runner.py`
y la herramienta MCP delega en ella.
