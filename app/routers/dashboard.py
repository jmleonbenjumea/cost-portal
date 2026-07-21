from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cost_engine import DEFAULT_PRICES, cache_savings, calculate_row_cost
from app.database import get_db
from app.formatting import mes_es
from app.models import CostConfig, DevLicense, Project
from app.templating import templates

router = APIRouter()


async def _load_prices(db: AsyncSession) -> dict:
    """Load price overrides from DB; fall back to DEFAULT_PRICES for missing models."""
    rows = (await db.execute(select(CostConfig))).scalars().all()
    prices = dict(DEFAULT_PRICES)
    from app.cost_engine import ModelPrice
    for r in rows:
        prices[r.model_name] = ModelPrice(
            r.price_input_mtok, r.price_output_mtok,
            r.price_cache_read_mtok, r.price_cache_creation_mtok,
            r.price_per_1k_pages,
        )
    return prices


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    month: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    prices = await _load_prices(db)

    now = datetime.now(UTC)

    # Parse selected month (YYYY-MM) or default to current month.
    if month:
        try:
            parsed = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
            month_start = parsed.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # End of selected month
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    # Available months for the selector (from first record up to current month)
    first_row = (await db.execute(
        text("SELECT MIN(timestamp) FROM api_audit_logs")
    )).scalar()

    # value = clave del filtro (YYYY-MM); label = mes en español para el desplegable.
    available_months: list[dict] = []
    if first_row:
        cursor = first_row.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC)
        current_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while cursor <= current_month:
            available_months.append({"value": cursor.strftime("%Y-%m"), "label": mes_es(cursor)})
            if cursor.month == 12:
                cursor = cursor.replace(year=cursor.year + 1, month=1)
            else:
                cursor = cursor.replace(month=cursor.month + 1)

    selected_month = month_start.strftime("%Y-%m")

    # Projects for filter dropdown
    projects = (await db.execute(select(Project).order_by(Project.name))).scalars().all()

    # Raw audit rows for selected month
    audit_rows = (await db.execute(
        text("""
            SELECT model_name, tokens_input, tokens_output,
                   tokens_cache_read, tokens_cache_creation, pages_processed,
                   servicio_externo, operacion, resultado, timestamp
            FROM api_audit_logs
            WHERE timestamp >= :month_start AND timestamp < :month_end AND resultado = 'OK'
            ORDER BY timestamp DESC
        """),
        {"month_start": month_start, "month_end": month_end},
    )).mappings().all()

    # Per-model totals this month
    model_totals: dict[str, dict] = {}
    total_month = 0.0
    total_cache_savings = 0.0

    for row in audit_rows:
        cost = calculate_row_cost(
            model_name=row["model_name"],
            tokens_input=row["tokens_input"],
            tokens_output=row["tokens_output"],
            tokens_cache_read=row["tokens_cache_read"],
            tokens_cache_creation=row["tokens_cache_creation"],
            pages_processed=row["pages_processed"],
            prices=prices,
        )
        total_month += cost
        total_cache_savings += cache_savings(
            model_name=row["model_name"],
            tokens_cache_read=row["tokens_cache_read"],
            prices=prices,
        )

        m = row["model_name"] or "unknown"
        if m not in model_totals:
            model_totals[m] = {"cost": 0.0, "calls": 0}
        model_totals[m]["cost"] += cost
        model_totals[m]["calls"] += 1

    # Daily costs for the selected month (chart)
    daily_rows = (await db.execute(
        text("""
            SELECT DATE(timestamp AT TIME ZONE 'UTC') AS day,
                   model_name, tokens_input, tokens_output,
                   tokens_cache_read, tokens_cache_creation, pages_processed
            FROM api_audit_logs
            WHERE timestamp >= :month_start AND timestamp < :month_end AND resultado = 'OK'
            ORDER BY day
        """),
        {"month_start": month_start, "month_end": month_end},
    )).mappings().all()

    daily_costs: dict[str, float] = {}
    for row in daily_rows:
        day = str(row["day"])
        cost = calculate_row_cost(
            model_name=row["model_name"],
            tokens_input=row["tokens_input"],
            tokens_output=row["tokens_output"],
            tokens_cache_read=row["tokens_cache_read"],
            tokens_cache_creation=row["tokens_cache_creation"],
            pages_processed=row["pages_processed"],
            prices=prices,
        )
        daily_costs[day] = daily_costs.get(day, 0.0) + cost

    chart_labels = sorted(daily_costs.keys())
    chart_values = [round(daily_costs[d], 4) for d in chart_labels]

    # Dev licenses total
    licenses = (await db.execute(
        select(DevLicense).where(DevLicense.active == True)
    )).scalars().all()
    # Con IVA: es lo que se paga de verdad, y así es comparable con el gasto de APIs.
    licenses_total = sum(lic.cost_monthly_gross_usd for lic in licenses)

    # Call count stats
    total_calls = len(audit_rows)
    error_count = (await db.execute(
        text("SELECT COUNT(*) FROM api_audit_logs WHERE timestamp >= :s AND timestamp < :e AND resultado = 'ERROR'"),
        {"s": month_start, "e": month_end},
    )).scalar() or 0

    return templates.TemplateResponse(request, "dashboard.html", {
        "total_month": round(total_month, 4),
        "licenses_total": round(licenses_total, 2),
        "grand_total": round(total_month + licenses_total, 2),
        "total_cache_savings": round(total_cache_savings, 4),
        "model_totals": {k: {"cost": round(v["cost"], 4), "calls": v["calls"]}
                         for k, v in sorted(model_totals.items(), key=lambda x: -x[1]["cost"])},
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "total_calls": total_calls,
        "error_count": error_count,
        "month_name": mes_es(month_start),
        "selected_month": selected_month,
        "available_months": available_months,
        "projects": projects,
    })
