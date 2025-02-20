# src/tastytrade/api/config.py

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    api_title: str = "TastyTrade API"
    api_description: str = "REST API for TastyTrade SDK"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    class Config:
        env_prefix = "TASTYTRADE_API_"
