from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET_KEY: str = "changeme_use_a_long_random_string_in_production"
    ALGORITHM: str = "HS256"
    DATABASE_URL: str = (
        "postgresql+asyncpg://capitalism_user:capitalism_pass@postgres_enterprise:5432/enterprise_management_db"
    )
    USER_SERVICE_URL: str = "http://user_management_service:8001"

    model_config = {"env_file": ".env"}


settings = Settings()
