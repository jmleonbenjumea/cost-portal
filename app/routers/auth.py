import secrets

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth_service import auth_service
from app.config import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["auth"])

_ERROR_MESSAGES = {
    "denied": "Tu cuenta no tiene acceso a este panel. Contacta con el administrador.",
    "auth": "No se pudo completar el inicio de sesión. Inténtalo de nuevo.",
}


def _login_html(error: str | None) -> str:
    """Render the branded Benjumea login page."""
    banner = ""
    if error:
        msg = _ERROR_MESSAGES.get(error, "Ha ocurrido un error.")
        banner = f'<div class="error">{msg}</div>'
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex, nofollow" />
  <title>Acceso · Control de Gastos IA · Benjumea</title>
  <link rel="icon" type="image/jpeg" href="/static/logo.jpg" />
  <style>
    :root {{ --navy:#01236c; --navy-2:#012d8a; --red:#a20000; --line:#e6e9ef; --muted:#6b7689; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      background: linear-gradient(135deg, var(--navy) 0%, var(--navy-2) 100%); color:#1a2233;
    }}
    .card {{
      background:#fff; width:100%; max-width:380px; margin:1.5rem; padding:2.5rem 2.25rem;
      border-radius:14px; box-shadow:0 20px 50px rgba(0,0,0,.25); text-align:center;
    }}
    .logo {{ height:46px; margin-bottom:1.5rem; }}
    h1 {{ font-size:1.15rem; margin:0 0 .35rem; color:var(--navy); }}
    p.sub {{ margin:0 0 1.75rem; color:var(--muted); font-size:.9rem; }}
    .btn {{
      display:flex; align-items:center; justify-content:center; gap:.6rem; width:100%;
      padding:.8rem 1rem; border:1px solid var(--line); border-radius:8px; background:#fff;
      color:#1a2233; font-size:.95rem; font-weight:600; cursor:pointer; text-decoration:none;
      transition:background .15s, border-color .15s;
    }}
    .btn:hover {{ background:#f6f8fc; border-color:#c9d2e3; }}
    .error {{
      background:#fdecee; color:var(--red); border:1px solid #f5c2cb; border-radius:8px;
      padding:.7rem .85rem; font-size:.85rem; margin-bottom:1.25rem; text-align:left;
    }}
    .foot {{ margin-top:1.75rem; font-size:.72rem; color:var(--muted); }}
  </style>
</head>
<body>
  <div class="card">
    <img class="logo" src="/static/logo.jpg" alt="Benjumea" />
    <h1>Control de Gastos IA</h1>
    <p class="sub">Accede con tu cuenta corporativa de Microsoft.</p>
    {banner}
    <a class="btn" href="/auth/login">
      <svg width="18" height="18" viewBox="0 0 21 21" aria-hidden="true">
        <rect x="1" y="1" width="9" height="9" fill="#f25022"/>
        <rect x="11" y="1" width="9" height="9" fill="#7fba00"/>
        <rect x="1" y="11" width="9" height="9" fill="#00a4ef"/>
        <rect x="11" y="11" width="9" height="9" fill="#ffb900"/>
      </svg>
      Iniciar sesión con Microsoft
    </a>
    <div class="foot">Acceso restringido al personal autorizado de Benjumea.</div>
  </div>
</body>
</html>"""


@router.get("/login", response_class=HTMLResponse, response_model=None)
async def login_page(request: Request) -> HTMLResponse | RedirectResponse:
    """Branded login landing page. Redirects to the dashboard if already signed in."""
    if request.session.get("user"):
        return RedirectResponse("/", status_code=302)
    return HTMLResponse(_login_html(request.query_params.get("error")))


@router.get("/auth/login")
async def auth_login(request: Request) -> RedirectResponse:
    """Start the OIDC flow: store state/nonce and redirect to Microsoft."""
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    request.session["oauth_nonce"] = nonce
    return RedirectResponse(auth_service.build_auth_url(state, nonce), status_code=302)


@router.get("/auth/callback")
async def auth_callback(request: Request) -> RedirectResponse:
    """Handle the redirect back from Microsoft: validate, check group, set session."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    sess_state = request.session.pop("oauth_state", None)
    nonce = request.session.pop("oauth_nonce", None)

    if not code or not state or not sess_state or not secrets.compare_digest(state, sess_state):
        logger.warning("auth.callback.bad_state")
        return RedirectResponse("/login?error=auth", status_code=302)

    try:
        claims = await auth_service.acquire_claims(code, nonce or "")
    except Exception as exc:
        # Cualquier fallo del intercambio (MSAL, red, validación) → login con error,
        # nunca un 500. Se registra tipo + mensaje para diagnóstico (sin traceback).
        logger.warning(
            "auth.callback.exchange_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return RedirectResponse("/login?error=auth", status_code=302)

    if not auth_service.is_authorized(claims):
        # Diagnóstico conciso para auditar denegaciones sin volcar el token completo.
        groups = claims.get("groups")
        logger.warning(
            "auth.callback.denied",
            oid=claims.get("oid"),
            tid_match=claims.get("tid") == settings.ms_tenant_id,
            has_groups_claim=groups is not None,
            num_groups=len(groups) if isinstance(groups, list) else None,
            group_present=(
                settings.portal_allowed_group_id in groups if isinstance(groups, list) else None
            ),
            groups_overage="_claim_names" in claims,
        )
        request.session.clear()
        return RedirectResponse("/login?error=denied", status_code=302)

    request.session["user"] = {
        "name": claims.get("name"),
        "email": claims.get("preferred_username") or claims.get("email"),
        "oid": claims.get("oid"),
    }
    logger.info("auth.login.ok", email=request.session["user"]["email"])
    return RedirectResponse("/", status_code=302)


@router.get("/auth/logout")
async def auth_logout(request: Request) -> RedirectResponse:
    """Clear the local session and return to the login page."""
    request.session.clear()
    return RedirectResponse("/login", status_code=302)
