from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str
    public_base_url: str = "http://localhost:8080"
    token_encryption_key: str = ""

    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    kick_client_id: str = ""
    kick_client_secret: str = ""
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    vk_client_id: str = ""
    vk_client_secret: str = ""
    trovo_client_id: str = ""
    trovo_client_secret: str = ""

    rawg_api_key: str = ""

    host: str = "0.0.0.0"
    port: int = 8080
    database_url: str = "sqlite+aiosqlite:///./data/bot.db"

    @property
    def oauth_callback_base(self) -> str:
        return self.public_base_url.rstrip("/") + "/oauth"


def get_settings() -> Settings:
    return Settings()
