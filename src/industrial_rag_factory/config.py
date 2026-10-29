"""Explicit environment configuration; API keys never committed."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = "./data/stage01.sqlite3"
    dense_backend: str = "hashing"
    dense_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    generator: str = "extractive"
    planner: str = "rules"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_api_key: str = ""
    tenant_id: str = "demo"
    groups: tuple[str, ...] = ("demo-readers",)
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 5000

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            db_path=os.getenv("IRF_DB_PATH", cls.db_path),
            dense_backend=os.getenv("IRF_DENSE_BACKEND", cls.dense_backend),
            dense_model=os.getenv("IRF_DENSE_MODEL", cls.dense_model),
            generator=os.getenv("IRF_GENERATOR", cls.generator),
            planner=os.getenv("IRF_PLANNER", cls.planner),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", cls.deepseek_base_url),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", cls.deepseek_model),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            tenant_id=os.getenv("IRF_TENANT_ID", "demo"),
            groups=tuple(x.strip() for x in os.getenv("IRF_GROUPS", "demo-readers").split(",") if x.strip()),
            environment=os.getenv("IRF_ENV", "development"),
            host=os.getenv("IRF_HOST", "127.0.0.1"),
            port=int(os.getenv("IRF_PORT", "5000")),
        )
        if settings.generator not in ("extractive", "deepseek"):
            raise ValueError("Invalid IRF_GENERATOR")
        if settings.planner not in ("rules", "deepseek"):
            raise ValueError("Invalid IRF_PLANNER")
        if settings.planner == "deepseek" and not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY required for DeepSeek planner")
        if settings.dense_backend not in ("none", "hashing", "sentence-transformers"):
            raise ValueError("Invalid IRF_DENSE_BACKEND")
        if settings.generator == "deepseek" and not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required to enable DeepSeek")
        return settings
