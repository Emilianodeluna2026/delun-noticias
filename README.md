# Noticias de reguladores (IOSCO)

Cada día, GitHub Actions lee las páginas de noticias de ~150 reguladores (lista en `sources.json`, generada desde `sources/fuentes.xlsx`), resume cada noticia nueva en 3-5 líneas en español con la API de Anthropic y publica una web estática con GitHub Pages.

## Puesta en marcha (una sola vez)

1. Crea un repositorio en GitHub y sube todo el contenido de esta carpeta.
2. **Settings → Secrets and variables → Actions → New repository secret**
   - Nombre: `ANTHROPIC_API_KEY`; valor: tu clave de https://console.anthropic.com
3. **Settings → Pages → Source: GitHub Actions**.
4. **Settings → Pages → Custom domain**: escribe tu dominio o subdominio (por ejemplo `noticias.delun.online`).
   En tu proveedor de DNS crea un registro `CNAME` de `noticias` hacia `TU_USUARIO.github.io`.
5. **Actions → Noticias diarias → Run workflow** para la primera ejecución. Después se lanza sola cada día a las 05:30 UTC.

## Ajustes (variables de entorno en `.github/workflows/noticias.yml`, sección `env`)

| Variable | Por defecto | Qué hace |
|---|---|---|
| `MAX_AGE_DAYS` | 3 | Ignora noticias con fecha más antigua |
| `MAX_NEW_PER_URL` | 5 | Máximo de noticias por URL y día |
| `MAX_SUMMARIES` | 400 | Tope de resúmenes por ejecución (controla el coste) |
| `KEEP_DAYS` | 30 | Días de histórico visibles en la web |
| `ANTHROPIC_MODEL` | claude-haiku-5-5 | Modelo para los resúmenes |

## Fuentes

- `sources.json` contiene cada institución con sus URLs y su estado (`ok`, `dudoso`, `sin_probar`, `roto`, `bloqueado`). Solo se leen las URLs con `"activa": true`.
- Tras cada ejecución, `site/data/health.json` lista las URLs que han fallado o no han devuelto enlaces. Es la guía para arreglar o sustituir fuentes.
- Si editas el Excel: `python scripts/build_sources.py`.

## Pruebas en local

```bash
pip install -r requirements.txt
python scripts/collect.py --no-llm --only 399,165   # sin API, solo dos instituciones
python -m http.server -d site 8000                  # abre http://localhost:8000
```
