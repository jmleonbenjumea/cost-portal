"""Tipo de cambio USD→EUR a partir del feed diario oficial del BCE.

El motor de costes (``app.cost_engine``) trabaja SIEMPRE en dólares: es la moneda en
la que facturan Anthropic, OpenAI y Azure, y en la que se guardan los precios en
``portal_cost_config``. El euro es solo presentación y se aplica en el borde, en los
filtros Jinja de ``app.templating``.

El feed del BCE (``eurofxref-daily.xml``) publica EUR→divisa una vez al día en días
hábiles, así que se cachea en memoria y se refresca en segundo plano desde el
lifespan de la app: ninguna petición del panel espera a la red. Si el feed falla se
conserva el último tipo bueno y, si nunca hubo ninguno, se cae a
``settings.usd_to_eur_fallback``.
"""

import asyncio
import time
from dataclasses import dataclass
from xml.etree import ElementTree

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

_ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_NS = {"ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}

_TTL_SECONDS = 6 * 3600        # el BCE publica ~16:00 CET; 4 comprobaciones al día sobran
_RETRY_SECONDS = 10 * 60       # tras un fallo de red se reintenta pronto
_TIMEOUT_SECONDS = 10.0
_MAX_BYTES = 256 * 1024        # el XML real ronda los 3 KB; corta cualquier sorpresa

SOURCE_ECB = "BCE"
SOURCE_FALLBACK = "valor de respaldo"


@dataclass(frozen=True)
class FxRate:
    """Tipo aplicado en el panel. ``rate_date`` es la fecha de publicación del BCE."""

    usd_to_eur: float
    rate_date: str
    source: str

    @property
    def is_official(self) -> bool:
        return self.source == SOURCE_ECB


_cache: FxRate | None = None
_next_refresh: float = 0.0
_lock = asyncio.Lock()


def current() -> FxRate:
    """Tipo vigente, sin tocar la red. Seguro de llamar desde plantillas."""
    return _cache or FxRate(settings.usd_to_eur_fallback, "", SOURCE_FALLBACK)


async def refresh(*, force: bool = False) -> FxRate:
    """Refresca el tipo si toca. Nunca lanza: ante un fallo devuelve el tipo vigente."""
    global _cache, _next_refresh

    if not force and time.monotonic() < _next_refresh:
        return current()

    async with _lock:
        # Otra corrutina pudo refrescar mientras esperábamos el lock.
        if not force and time.monotonic() < _next_refresh:
            return current()
        try:
            rate = await _fetch_ecb()
        except Exception as exc:
            _next_refresh = time.monotonic() + _RETRY_SECONDS
            logger.warning(
                "fx.refresh_failed", error=str(exc), vigente=current().source,
            )
            return current()

        _cache = rate
        _next_refresh = time.monotonic() + _TTL_SECONDS
        logger.info("fx.refreshed", usd_to_eur=rate.usd_to_eur, fecha=rate.rate_date)
        return rate


async def _fetch_ecb() -> FxRate:
    """Descarga y parsea el XML diario del BCE. Devuelve el tipo USD→EUR."""
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        resp = await client.get(_ECB_DAILY_URL)
    resp.raise_for_status()
    if len(resp.content) > _MAX_BYTES:
        raise ValueError(f"respuesta del BCE inesperadamente grande ({len(resp.content)} bytes)")
    return parse_ecb_xml(resp.content)


def parse_ecb_xml(payload: bytes) -> FxRate:
    """Extrae el tipo USD del ``eurofxref-daily.xml``.

    El feed da EUR→divisa (``rate="1.1612"`` = 1 EUR son 1,1612 USD), así que el tipo
    que necesita el panel es su inverso.
    """
    root = ElementTree.fromstring(payload)
    day_cube = root.find("ecb:Cube/ecb:Cube", _NS)
    if day_cube is None:
        raise ValueError("XML del BCE sin cubo de fecha")

    usd_cube = next(
        (c for c in day_cube.findall("ecb:Cube", _NS) if c.get("currency") == "USD"), None
    )
    if usd_cube is None:
        raise ValueError("XML del BCE sin cotización USD")

    eur_to_usd = float(usd_cube.get("rate", "0"))
    if eur_to_usd <= 0:
        raise ValueError(f"cotización USD no válida: {usd_cube.get('rate')!r}")

    return FxRate(
        usd_to_eur=1.0 / eur_to_usd,
        rate_date=day_cube.get("time", ""),
        source=SOURCE_ECB,
    )


async def refresh_loop() -> None:
    """Tarea de fondo del lifespan: mantiene el tipo fresco sin bloquear peticiones."""
    while True:
        await refresh()
        await asyncio.sleep(_RETRY_SECONDS)


def _reset_for_tests() -> None:
    """Limpia la caché del módulo (solo para tests)."""
    global _cache, _next_refresh
    _cache, _next_refresh = None, 0.0
