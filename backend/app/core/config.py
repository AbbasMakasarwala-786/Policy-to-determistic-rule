from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="AP Policy Rule Extraction API", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    mistral_api_key: str | None = Field(default=None, alias="MISTRAL_API_KEY")
    mistral_model: str = Field(default="mistral-small-latest", alias="MISTRAL_MODEL")
    mistral_base_url: str = Field(
        default="https://api.mistral.ai/v1",
        alias="MISTRAL_BASE_URL",
    )
    llm_timeout_seconds: int = Field(default=60, alias="LLM_TIMEOUT_SECONDS")
    enable_llm: bool = Field(default=True, alias="ENABLE_LLM")

    smtp_host: str | None = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str | None = Field(default=None, alias="SMTP_USERNAME")
    smtp_password: str | None = Field(default=None, alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="ap-policy-bot@example.com", alias="SMTP_FROM")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    default_notification_to: str = Field(
        default="finance_controller@example.com,internal_audit@example.com",
        alias="DEFAULT_NOTIFICATION_TO",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def default_notification_recipients(self) -> list[str]:
        return [item.strip() for item in self.default_notification_to.split(",") if item.strip()]

    @property
    def can_send_email(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def llm_enabled_and_configured(self) -> bool:
        return self.enable_llm and bool(self.mistral_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
