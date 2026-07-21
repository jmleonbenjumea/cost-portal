from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CostConfig, DevLicense, Project
from app.templating import templates

router = APIRouter(prefix="/config")


@router.get("", response_class=HTMLResponse)
async def config_page(request: Request, db: AsyncSession = Depends(get_db)):
    prices = (await db.execute(select(CostConfig).order_by(CostConfig.provider, CostConfig.model_name))).scalars().all()
    projects = (await db.execute(select(Project).order_by(Project.name))).scalars().all()
    licenses = (await db.execute(select(DevLicense).order_by(DevLicense.provider, DevLicense.name))).scalars().all()
    return templates.TemplateResponse(request, "config.html", {
        "prices": prices,
        "projects": projects,
        "licenses": licenses,
    })


# ── Cost config ──────────────────────────────────────────────────────────────

@router.post("/precios/upsert")
async def upsert_price(
    model_name: str = Form(...),
    provider: str = Form(...),
    price_input_mtok: float = Form(0.0),
    price_output_mtok: float = Form(0.0),
    price_cache_read_mtok: float = Form(0.0),
    price_cache_creation_mtok: float = Form(0.0),
    price_per_1k_pages: float = Form(0.0),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        select(CostConfig).where(CostConfig.model_name == model_name)
    )).scalar_one_or_none()
    if existing:
        existing.provider = provider
        existing.price_input_mtok = price_input_mtok
        existing.price_output_mtok = price_output_mtok
        existing.price_cache_read_mtok = price_cache_read_mtok
        existing.price_cache_creation_mtok = price_cache_creation_mtok
        existing.price_per_1k_pages = price_per_1k_pages
        existing.notes = notes or None
    else:
        db.add(CostConfig(
            model_name=model_name, provider=provider,
            price_input_mtok=price_input_mtok, price_output_mtok=price_output_mtok,
            price_cache_read_mtok=price_cache_read_mtok,
            price_cache_creation_mtok=price_cache_creation_mtok,
            price_per_1k_pages=price_per_1k_pages, notes=notes or None,
        ))
    await db.commit()
    return RedirectResponse("/config", status_code=303)


# ── Projects ──────────────────────────────────────────────────────────────────

@router.post("/proyectos/upsert")
async def upsert_project(
    project_id: str = Form(""),
    name: str = Form(...),
    description: str = Form(""),
    color: str = Form("#6366f1"),
    budget_monthly: float = Form(0.0),
    db: AsyncSession = Depends(get_db),
):
    if project_id:
        proj = (await db.get(Project, project_id))
        if proj:
            proj.name = name
            proj.description = description or None
            proj.color = color
            proj.budget_monthly = budget_monthly or None
    else:
        db.add(Project(
            name=name, description=description or None,
            color=color, budget_monthly=budget_monthly or None,
        ))
    await db.commit()
    return RedirectResponse("/config", status_code=303)


# ── Dev licenses ─────────────────────────────────────────────────────────────

@router.post("/licencias/upsert")
async def upsert_license(
    license_id: str = Form(""),
    name: str = Form(...),
    provider: str = Form(...),
    plan: str = Form(...),
    cost_monthly_usd: float = Form(...),
    tax_rate_pct: float = Form(21.0),
    assignee: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if license_id:
        lic = await db.get(DevLicense, license_id)
        if lic:
            lic.name = name
            lic.provider = provider
            lic.plan = plan
            lic.cost_monthly_usd = cost_monthly_usd
            lic.tax_rate_pct = tax_rate_pct
            lic.assignee = assignee or None
            lic.notes = notes or None
    else:
        db.add(DevLicense(
            name=name, provider=provider, plan=plan,
            cost_monthly_usd=cost_monthly_usd, tax_rate_pct=tax_rate_pct,
            assignee=assignee or None, notes=notes or None,
        ))
    await db.commit()
    return RedirectResponse("/config", status_code=303)


@router.post("/licencias/{license_id}/toggle")
async def toggle_license(license_id: str, db: AsyncSession = Depends(get_db)):
    lic = await db.get(DevLicense, license_id)
    if lic:
        lic.active = not lic.active
        await db.commit()
    return RedirectResponse("/config", status_code=303)
