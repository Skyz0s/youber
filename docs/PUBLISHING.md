# Publicación en PyPI — BARF

Guía para publicar el paquete `youber` en PyPI (o TestPyPI). El proyecto ya
está preparado: `pyproject.toml` con metadatos, clasificadores, URLs,
licencia MIT y entry points.

## Requisitos

```bash
pip install build twine
```

## Pasos

### 1. Versión

La versión vive en `pyproject.toml` (`[project] version`) y en
`src/youber/__init__.py` (`__version__`). Mantenlas sincronizadas.

Sugerencia de versionado semántico:

- `0.1.0` — primera publicación (Alpha)
- `0.2.0` — nuevas funcionalidades
- `1.0.0` — API estable

### 2. Construir

```bash
python -m build
```

Genera `dist/youber-<version>.tar.gz` y `.whl`.

### 3. Probar en TestPyPI

```bash
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ youber
```

### 4. Publicar

```bash
twine upload dist/*
```

### 5. Verificar

```bash
pip install youber
youber-audit --help
youber-client --help
```

### 6. Publicación automática desde GitHub (opcional, recomendado)

El repo incluye `.github/workflows/publish.yml`: al crear un tag `v*` (p. ej.
`git tag v0.1.0 && git push --tags`), GitHub Actions construye el paquete y
lo publica en PyPI usando **Trusted Publishing** (sin tokens manuales).

Requisitos:

1. Habilita Trusted Publishing en el proyecto PyPI
   (<https://docs.pypi.org/trusted-publishers/>) apuntando a
   `owner/repo` → workflow `publish.yml`.
2. Opcional: crea también un release en GitHub con el tag para el CHANGELOG.

También puedes publicar manualmente con `twine upload dist/*`.

## Notas

- **Nombre en PyPI**: `youber` debe estar libre. Comprueba
  `https://pypi.org/project/youber/` antes de publicar.
- **README**: PyPI renderiza `README.md` (campo `readme` en pyproject).
  Recuerda que los enlaces relativos a `docs/` no funcionan en PyPI; usa
  enlaces absolutos del repo si quieres que apunten a GitHub.
- **Clasificadores**: ya incluidos (Alpha, Education, MIT, Python 3.11/3.12).
- **Peso del paquete**: `axe.min.js` (~550 KB) se incluye como asset del
  paquete; es intencional (auditorías offline deterministas).
- **CI**: el workflow de GitHub Actions verifica lint, tipos y tests antes de
  cada push; es una buena puerta previa a cada release.

## Checklist previo a publicar

- [ ] `ruff check src/ tests/ examples/` sin errores
- [ ] `mypy src/` sin errores
- [ ] `pytest tests/` en verde
- [ ] Versión sincronizada en pyproject y `__init__.py`
- [ ] CHANGELOG actualizado (si existe)
- [ ] README con enlaces absolutos para PyPI
