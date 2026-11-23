import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from pydantic import Field, field_validator
from office.models import StrictModel

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("JOB_OFFICE_DATA_DIR", str(ROOT / "data")))


class Settings(StrictModel):
    api_url: str = "http://localhost:11434"
    model: str = Field(default="qwen3-office", min_length=1)
    timeout_seconds: int = Field(default=300, ge=30, le=900)

    @field_validator("api_url")
    @classmethod
    def local_only(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise ValueError("Use a local HTTP Ollama URL, e.g. http://localhost:11434")
        _ = parsed.port
        return value.rstrip("/")


def load_settings() -> Settings:
    path = DATA / "settings.json"
    return Settings.model_validate_json(path.read_text("utf-8")) if path.exists() else Settings()


def save_settings(settings: Settings):
    DATA.mkdir(parents=True, exist_ok=True)
    temp = DATA / "settings.tmp"
    temp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    temp.replace(DATA / "settings.json")
