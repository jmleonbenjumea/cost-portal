"""Formato numérico y de fechas en convención europea (es-ES).

Funciones puras, sin dependencias de la app: punto como separador de millares y coma
como separador decimal (``1.234,56``), fechas ``dd/mm/aaaa`` y meses en español. Se
usa ``str.translate`` en vez de ``locale`` porque el locale ``es_ES`` no está
garantizado en el contenedor de despliegue.
"""

from datetime import date, datetime

# Intercambia los separadores del formato inglés que produce f"{v:,.2f}".
_SWAP_SEPARATORS = str.maketrans({",": ".", ".": ","})

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def format_number_es(value: float | int | None, decimals: int = 0) -> str:
    """``1234.5`` → ``'1.234,50'``. ``None`` → ``'—'``."""
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}".translate(_SWAP_SEPARATORS)


def mes_es(value: date | datetime) -> str:
    """``date(2026, 7, 1)`` → ``'julio 2026'``."""
    return f"{MESES[value.month - 1]} {value.year}"


def fecha_es(value: str | date | datetime | None, con_anio: bool = True) -> str:
    """Fecha ISO (o ``date``) → ``'21/07/2026'``; con ``con_anio=False`` → ``'21/07'``.

    Acepta cadenas porque las etiquetas de las gráficas llegan como ISO desde SQL.
    """
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    return value.strftime("%d/%m/%Y") if con_anio else value.strftime("%d/%m")
