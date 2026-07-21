from pathlib import Path

from fastapi.templating import Jinja2Templates

from app import fx
from app.formatting import fecha_es, format_number_es, mes_es

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _eur(usd: float | None, decimals: int = 2) -> str:
    """Importe en USD → texto en euros al cambio vigente: ``'1.234,56 €'``."""
    return f"{format_number_es((usd or 0.0) * fx.current().usd_to_eur, decimals)} €"


def _eur_num(usd: float | None, decimals: int = 6) -> float:
    """Importe en USD → número en euros, para series de gráficas (las formatea JS)."""
    return round((usd or 0.0) * fx.current().usd_to_eur, decimals)


# Toda cifra monetaria del panel pasa por `eur`/`eur_num`: el cambio se aplica en un
# único sitio y los routers siguen entregando USD.
templates.env.filters["eur"] = _eur
templates.env.filters["eur_num"] = _eur_num
templates.env.filters["num"] = format_number_es
templates.env.filters["fecha"] = fecha_es
templates.env.filters["mes"] = mes_es
templates.env.globals["fx"] = fx.current
