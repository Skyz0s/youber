# Bot de Telegram (`youber.telegram`)

Controla el framework BARF desde Telegram: investigar canales, buscar y
sugerir música del catálogo, ejecutar el flujo completo de edición,
renderizar proyectos, consultar tareas, programar y subir vídeos a YouTube.

## Arrancar el bot

```bash
pip install -e ".[dev]"   # incluye python-telegram-bot
export TELEGRAM_BOT_TOKEN="123456:ABC..."
python -c "from youber.telegram import build_application; build_application('$TELEGRAM_BOT_TOKEN').run_polling()"
```

El token se obtiene de **@BotFather** en Telegram (crear bot → token).

## Comandos

| Comando | Descripción |
|---|---|
| `/research <canal>` | Investiga un canal (`/research @python`) |
| `/music search <término>` | Busca en el catálogo (`/music search piano`) |
| `/music suggest <mood>` | Sugiere música por mood (`/music suggest épica`) |
| `/workflow <canal> [--edit] [--upload]` | Flujo completo (`/workflow @python --edit`) |
| `/edit <proyecto.json>` | Renderiza un proyecto de vídeo |
| `/status` | Estado de las tareas en curso |
| `/schedule list` | Lista tareas programadas |
| `/schedule add <canal> [--daily]` | Programa una tarea |
| `/schedule remove <id>` | Elimina una tarea programada |
| `/upload <video> --title "..."` | Sube un vídeo a YouTube |
| `/help` | Muestra la ayuda |

## Estructura

| Módulo | Responsabilidad |
|---|---|
| `messages.py` | Formateo de mensajes (HTML): canales, pistas, tareas, ayuda |
| `keyboards.py` | Teclados inline: moods, privacidad, confirmaciones |
| `handlers.py` | Los manejadores de comandos (delegan en los módulos del framework) |
| `commands.py` | Registro de comandos + `register_handlers()` + `build_application()` |

## Detalles de implementación

- **Progreso en comandos largos**: `/research`, `/workflow`, `/edit` y
  `/upload` responden primero `🔄 ...` y luego el resultado, para que el
  usuario sepa que la tarea está en marcha.
- **Tareas en curso**: los comandos largos se registran en `ACTIVE_TASKS`
  y `/status` los muestra (se limpian al terminar).
- **Teclados inline**: `/music suggest` usa `mood_keyboard()` (un botón por
  estado de ánimo); el callback `mood:<valor>` responde con sugerencias.
  También hay `privacy_keyboard()` (public/unlisted/private) y
  `confirm_keyboard()` (✅/❌) listos para usar en subidas.
- **HTML seguro**: `escape_html()` evita HTML injection en los mensajes.
- **Programación**: `TaskStore` guarda las tareas de `/schedule` en
  `~/.youber/tasks.json` (cadence `once` o `daily`). La ejecución periódica
  real llega con el módulo de Programación de la Fase 11.
- **Música**: el catálogo se busca en `YOUBER_MUSIC_DIR` (por defecto
  `music/`); los handlers abren y cierran la librería en cada llamada.

## Configuración

| Variable | Uso |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot (para `build_application`) |
| `YOUBER_MUSIC_DIR` | Directorio del catálogo de música (default `music`) |
| `YOUBER_TASKS_FILE` | Fichero JSON de tareas programadas (default `~/.youber/tasks.json`) |

## Ética

El bot es una **interfaz de control** del framework: solo opera con contenido
propio o con licencia (investigación de datos públicos, música del catálogo,
vídeos propios). Sin spam, sin scraping abusivo y sin manipulación de
métricas. El bot respeta los mismos límites que el resto de BARF.
