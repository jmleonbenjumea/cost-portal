# cost-portal

Portal web interno de **Benjumea** para monitorizar el gasto en APIs de IA (Anthropic, OpenAI, Azure Document Intelligence) y licencias de desarrollo.

## Contexto general

Este portal es un servicio satélite de `siniestros-automation`. Comparte la misma base de datos PostgreSQL y lee en modo solo lectura la tabla `api_audit_logs` que escribe el servicio principal. Las tablas propias usan el prefijo `portal_`.

Corre en el **puerto 8001** (configurable vía `PORTAL_PORT` en `.env`).

## Stack

- **FastAPI** + **Jinja2** — SSR, sin JavaScript framework
- **SQLAlchemy 2.0 async** + **asyncpg** + **PostgreSQL**
- **Alembic** — migraciones
- **structlog** — logging estructurado
- **pydantic-settings** — configuración desde `.env`
- **Python ≥ 3.12**

## Diseño visual

Tema corporativo Benjumea, alineado con `api-docs-portal`:

| Token | Valor | Uso |
|---|---|---|
| `--navy` | `#01236c` | Color primario, headings, nav activo, botones |
| `--red` | `#a20000` | Cabeceras de tabla (`section-label`), errores |
| `--orange` | `#f08a12` | Cache savings, warnings |
| `--text` | `#383838` | Texto cuerpo |
| `--muted` | `#6b7280` | Texto secundario |
| `--bg` | `#f4f5f8` | Fondo de página |
| `--bg-card` | `#ffffff` | Fondo de cards/sidebar |
| `--border` | `#dde1ea` | Bordes |

- Borde navy de 3px en la parte superior de toda la página (via `body::before`)
- Logo de `/static/logo.jpg` en la cabecera del sidebar
- Tailwind CDN con config block que remapea la paleta `gray` e `indigo` al tema claro
- ApexCharts con `tooltip.theme: "light"` y colores navy/naranja

## Estructura

```
app/
  main.py          # FastAPI app, lifespan, seeds de datos iniciales
  config.py        # Settings (DATABASE_URL, PORTAL_PORT, ENVIRONMENT)
  database.py      # Engine async, AsyncSessionLocal, Base, get_db
  models.py        # Tablas propias: Project, CostConfig, DevLicense
  cost_engine.py   # Cálculo de costes puro — sin DB ni side effects
  fx.py            # Tipo USD→EUR desde el feed diario del BCE (caché en memoria)
  formatting.py    # Formato es-ES puro: 1.234,56 · dd/mm/aaaa · meses en español
  templating.py    # Jinja2Templates + filtros eur / eur_num / num / fecha / mes
  routers/
    dashboard.py      # GET /  — resumen del mes, gráfica 30 días
    registro.py       # GET /registro — tabla paginada de api_audit_logs
    proyectos.py      # GET /proyectos — vista por proyecto con mini-gráfica
    config_router.py  # GET+POST /config — precios, proyectos, licencias

templates/
  base.html
  dashboard.html
  registro.html
  proyectos.html
  config.html

alembic/
  versions/0001_initial_portal_tables.py  # Única migración: crea las 3 tablas portal_*
```

## Tablas de base de datos

### Propias (portal_*)
| Tabla | Propósito |
|---|---|
| `portal_projects` | Proyectos de facturación (Siniestros Automation, futuras fases) |
| `portal_cost_config` | Precios por modelo, editables desde la UI |
| `portal_dev_licenses` | Licencias fijas mensuales (Claude Max, Power Automate…) |

### Externas (solo lectura)
| Tabla | Propósito |
|---|---|
| `api_audit_logs` | Registros de uso de APIs — escrita por `siniestros-automation` |

Campos clave de `api_audit_logs`: `id`, `proyecto`, `conversation_id`, `timestamp`, `servicio_externo`, `operacion`, `model_name`, `tokens_input`, `tokens_output`, `tokens_cache_read`, `tokens_cache_creation`, `pages_processed`, `pii_anonimizado`, `duracion_ms`, `resultado` (`OK`/`ERROR`), `codigo_error`.

**Imputación de coste por proyecto**: se hace por `api_audit_logs.proyecto = portal_projects.name` (igualdad directa, **sin JOINs**). El repo `siniestros-automation` rellena `proyecto` con el nombre del proyecto ("Siniestros Automation"). Renombrar un proyecto exige renombrar también el valor `proyecto` de sus filas (migración coordinada en ambos repos — ver `0003`).

## Datos seeded al arrancar

El lifespan de la app hace seed condicional (solo si las tablas están vacías):

- **Proyecto:** "Siniestros Automation" — budget $100/mes, color `#6366f1`
- **Licencias:** Claude Max 5x ($100/mes), Power Automate Premium ($15/mes)
- **Precios:** todos los modelos de `DEFAULT_PRICES` en `cost_engine.py`

## Lógica de coste

`app/cost_engine.py` contiene dos funciones puras:

- `calculate_row_cost(...)` — devuelve el coste USD de una fila de `api_audit_logs`
- `cache_savings(...)` — ahorro USD por cache hits vs. precio input completo

Los precios se cargan de `portal_cost_config` en cada request (fallback a `DEFAULT_PRICES`). Los precios son en USD por millón de tokens (`price_*_mtok`). Para OCR se usa `price_per_1k_pages`.

## Divisa y formato

El panel se muestra **en euros y en formato europeo** (`1.234,56 €`, fechas `dd/mm/aaaa`,
meses en español), pero **el motor de costes y los precios siguen en USD**: es la moneda
en la que facturan Anthropic, OpenAI y Azure y en la que se guarda `portal_cost_config`.

La conversión ocurre **solo en el borde**, en los filtros Jinja de `app/templating.py`:

| Filtro | Uso |
|---|---|
| `eur(usd, decimals=2)` | Importe USD → texto `'1.234,56 €'` |
| `eur_num(usd, decimals=6)` | Importe USD → número en € para series de gráficas |
| `num(valor, decimals=0)` | Cifra no monetaria (tokens, llamadas) en formato es-ES |
| `fecha(valor, con_anio=True)` | ISO o `date` → `21/07/2026` (o `21/07`) |
| `mes(fecha)` | → `julio 2026` |

Regla: **ningún router formatea dinero**; entrega USD y la plantilla aplica `eur`. En JS,
las series ya llegan convertidas y se formatean con el helper `fmtEur(v, d)` de `base.html`.

El tipo lo publica el BCE a diario (`eurofxref-daily.xml`, EUR→divisa; se invierte). Se
cachea 6 h en memoria y lo refresca una tarea de fondo del lifespan, así que **ninguna
petición del panel espera a la red**. Si el feed falla se conserva el último tipo bueno y,
si nunca hubo ninguno, se usa `USD_TO_EUR_FALLBACK`. El tipo vigente y su fecha se
muestran en el pie del sidebar.

Los formularios de `/config` (precios, presupuestos, licencias) **se siguen introduciendo
en USD** — es la tarifa del proveedor —; el panel los muestra convertidos.

El CSV de `/registro/csv` también sale en convención española: separador `;`, coma
decimal, BOM UTF-8 y columnas `coste_eur`, `coste_usd` y `tipo_cambio_usd_eur`.

## Cómo arrancar

```bash
# Instalar dependencias
pip install -e .

# Configurar .env (copiar .env.example)
cp .env.example .env

# Aplicar migración (la app también crea tablas vía create_all al arrancar)
alembic upgrade head

# Arrancar
python -m app.main
# o
uvicorn app.main:app --reload --port 8001
```

## Autenticación

HTTP Basic Auth vía `app/auth.py`. Credenciales configurables en `.env`:
```
PORTAL_USER=admin
PORTAL_PASSWORD=changeme
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

- `tests/test_cost_engine.py` — tests unitarios de cálculo de costes (sin DB)
- `tests/test_formatting.py` — formato es-ES y parseo del XML del BCE (sin red)
- `tests/test_routers.py` — tests de rutas HTTP con SQLite en memoria (sin PostgreSQL)
