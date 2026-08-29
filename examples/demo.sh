#!/usr/bin/env bash
# ============================================================
# Demo de BARF / youber — versión Linux/macOS
# Uso: ./examples/demo.sh [URL]
#   (URL por defecto: https://example.com)
# Pausas entre pasos para poder comentar; desactívalas con:
#   DEMO_FAST=1 ./examples/demo.sh
# ============================================================
set -euo pipefail

URL="${1:-https://example.com}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Localizar el entorno: venv del proyecto o instalación global (pip install youber)
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
  BIN="$ROOT/.venv/bin"
else
  PY="python3"
  BIN=""
fi
AUDIT="${BIN:+$BIN/}youber-audit"
SANDBOX="${BIN:+$BIN/}youber-sandbox"

pause() {
  if [[ "${DEMO_FAST:-0}" != "1" ]]; then
    read -rp "  [Enter] siguiente paso..."
  fi
}

banner() {
  echo "============================================================"
  echo "  BARF / youber — Browser Automation Research Framework"
  echo "============================================================"
  echo "  URL de la demo: $URL"
  echo ""
}

banner

echo ""
echo "[1/3] Auditoría de accesibilidad (axe-core + WCAG 2.1/2.2)"
echo "------------------------------------------------------------"
"$AUDIT" "$URL"
pause

echo ""
echo "[2/3] Sandbox: región JP + iPhone + red 3g"
echo "------------------------------------------------------------"
"$SANDBOX" --url "$URL" --region JP --device iPhone --speed 3g
pause

echo ""
echo "[3/3] Cliente MCP end-to-end (servidor real por stdio)"
echo "------------------------------------------------------------"
"$PY" "$ROOT/examples/demo_mcp.py" "$URL"
pause

echo ""
echo "============================================================"
echo "  Demo completada ✅"
echo "  - Reporte Markdown en: $ROOT/reports/"
echo "  - Proyecto: https://github.com/Skyz0s/youber"
echo "  - PyPI:     pip install youber"
echo "============================================================"
