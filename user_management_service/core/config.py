from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET_KEY: str = "changeme_use_a_long_random_string_in_production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    DATABASE_URL: str = (
        "postgresql+asyncpg://capitalism_user:capitalism_pass@postgres:5432/user_management_db"
    )

    model_config = {"env_file": ".env"}


settings = Settings()
