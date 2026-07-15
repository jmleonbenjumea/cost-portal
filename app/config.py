from pydantic import model_validator
from pydantic_settings import BaseSettings

_WEAK_PASSWORDS = {"", "benjuema", "changeme", "admin", "password"}


class Settings(BaseSettings):
    database_url: str
    portal_port: int = 8001
    environment: str = "development"
    portal_user: str = "admin"
    portal_password: str = "benjuema"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def _no_weak_password_in_prod(self) -> "Settings":
        """En producción no se arranca con una password de panel débil/por defecto."""
        if self.environment.lower() != "development" and self.portal_password in _WEAK_PASSWORDS:
            raise ValueError(
                "PORTAL_PASSWORD débil o por defecto: define una fuerte en producción."
            )
        return self


settings = Settings()
