from pydantic import model_validator
from pydantic_settings import BaseSettings

_WEAK_PASSWORDS = {"", "benjuema", "changeme", "admin", "password"}


class Settings(BaseSettings):
    database_url: str
    portal_port: int = 8001
    environment: str = "development"
    portal_user: str = "admin"
    portal_password: str = "benjuema"

    # ── SSO con Microsoft Entra ID (opt-in) ───────────────────────────────────
    # Si portal_sso_enabled=true, el panel exige login con Microsoft restringido al
    # tenant + un grupo de seguridad; el HTTP Basic (portal_user/portal_password)
    # queda como acceso break-glass de emergencia. Reutiliza el App Registration de
    # correo de siniestros-automation (ms_client_id/secret/tenant): mismos valores.
    ms_tenant_id: str = ""
    ms_client_id: str = ""
    ms_client_secret: str = ""
    portal_sso_enabled: bool = False
    # Redirect URI registrado en el App Registration (…/auth/callback).
    portal_redirect_uri: str = ""
    # Object ID del grupo de seguridad de Entra cuyos miembros pueden entrar.
    portal_allowed_group_id: str = ""
    # Secreto para firmar la cookie de sesión (estable entre workers).
    session_secret: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def is_development(self) -> bool:
        """True cuando se ejecuta en un entorno de desarrollo."""
        return self.environment.lower() == "development"

    @model_validator(mode="after")
    def _no_weak_password_in_prod(self) -> "Settings":
        """En producción no se arranca con una password de panel débil/por defecto."""
        if not self.is_development and self.portal_password in _WEAK_PASSWORDS:
            raise ValueError(
                "PORTAL_PASSWORD débil o por defecto: define una fuerte en producción."
            )
        return self

    @model_validator(mode="after")
    def _sso_config_complete_in_prod(self) -> "Settings":
        """Si el SSO está activado en producción, exigir su configuración completa.

        El break-glass HTTP Basic falla en abierto (siempre disponible), así que un
        SSO a medias dejaría la puerta principal sin cerrar sin que nadie lo note.
        """
        if not self.is_development and self.portal_sso_enabled:
            missing = [
                name
                for name, value in (
                    ("MS_TENANT_ID", self.ms_tenant_id),
                    ("MS_CLIENT_ID", self.ms_client_id),
                    ("MS_CLIENT_SECRET", self.ms_client_secret),
                    ("PORTAL_REDIRECT_URI", self.portal_redirect_uri),
                    ("PORTAL_ALLOWED_GROUP_ID", self.portal_allowed_group_id),
                    ("SESSION_SECRET", self.session_secret),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    f"PORTAL_SSO_ENABLED=true pero faltan variables: {', '.join(missing)}."
                )
        return self


settings = Settings()
