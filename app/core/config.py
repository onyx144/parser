from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

class Settings(BaseSettings):
    app_name: str = "Ultimate Parser FastAPI"
    app_host: str = "0.0.0.0"
    app_port: int = 8088
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "temp_user"
    mysql_password: str = "temp_password"
    mysql_database: str = "ultimate_parser"
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
            drivername="mysql+aiomysql",
            username=self.mysql_user,
            password=self.mysql_password,
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.mysql_database,
            query={"charset": "utf8mb4"},
        )

    @property
    def redacted_database_url(self) -> str:
        return f"mysql+aiomysql://{self.mysql_user}:***@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"

settings = Settings()
