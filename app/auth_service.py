import asyncio
from typing import Any

import msal
import structlog

from app.config import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# openid/profile/email los añade MSAL implícitamente en el flujo de código de
# autorización; pedimos User.Read para obtener también un token de Graph (no
# imprescindible hoy, pero útil si más adelante se consulta /me).
_SCOPES = ["User.Read"]


class AuthService:
    """Inicio de sesión interactivo con Microsoft Entra ID (OIDC, authorization code).

    Single-tenant: la *authority* se fija al tenant configurado, por lo que **solo**
    usuarios de esa organización pueden autenticarse. La pertenencia al grupo se
    comprueba contra el claim ``groups`` del ID token (validado por MSAL).

    Idéntico al de siniestros-automation: ambos reutilizan el mismo App Registration.
    """

    def __init__(self) -> None:
        # Perezoso: la app MSAL solo se crea en el primer login (en dev con tenant
        # placeholder no se llega a usar).
        self._msal_app: msal.ConfidentialClientApplication | None = None

    def _app(self) -> msal.ConfidentialClientApplication:
        if self._msal_app is None:
            self._msal_app = msal.ConfidentialClientApplication(
                client_id=settings.ms_client_id,
                authority=f"https://login.microsoftonline.com/{settings.ms_tenant_id}",
                client_credential=settings.ms_client_secret,
            )
        return self._msal_app

    def build_auth_url(self, state: str, nonce: str) -> str:
        """Build the Microsoft authorization URL to redirect the user to."""
        return self._app().get_authorization_request_url(
            scopes=_SCOPES,
            state=state,
            nonce=nonce,
            redirect_uri=settings.portal_redirect_uri,
            prompt="select_account",
        )

    async def acquire_claims(self, code: str, nonce: str) -> dict[str, Any]:
        """Exchange the auth code for tokens and return the validated ID token claims.

        MSAL valida firma, issuer, audience y nonce del ID token. Las llamadas de MSAL
        son síncronas → se ejecutan en un hilo para no bloquear el event loop.

        Raises:
            RuntimeError: si el intercambio del código falla.
        """
        result: dict[str, Any] | None = await asyncio.to_thread(
            self._app().acquire_token_by_authorization_code,
            code,
            scopes=_SCOPES,
            redirect_uri=settings.portal_redirect_uri,
            nonce=nonce,
        )
        if "id_token_claims" not in (result or {}):
            error = (result or {}).get("error_description") or (result or {}).get(
                "error", "unknown"
            )
            raise RuntimeError(f"Auth code exchange failed: {error}")
        return result["id_token_claims"]  # type: ignore[index]

    def is_authorized(self, claims: dict[str, Any]) -> bool:
        """True si el usuario es del tenant correcto Y pertenece al grupo permitido."""
        if claims.get("tid") != settings.ms_tenant_id:
            return False
        if not settings.portal_allowed_group_id:
            return False
        groups = claims.get("groups") or []
        return settings.portal_allowed_group_id in groups


auth_service = AuthService()
