from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./senai_crm.db"
    environment: str = "development"

    # Gemini API — required for Phase 2 classification
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # Streaming simulator: emails per second
    simulator_rate: float = 1.0

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
