from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    app_name: str = "Ultimate Parser FastAPI"
    app_host: str = "0.0.0.0"
    app_port: int = 8090

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_user: str = "ultimate_parser_user"
    postgres_password: str = "change_me_pg_temp"
    postgres_database: str = "ultimate_parser"

    ai_api_base: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: int = 60
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def sqlalchemy_database_url(self):
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_database,
        )

    @property
    def redacted_database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:***@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"


settings = Settings()
