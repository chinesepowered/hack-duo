"""Settings loaded from .env (never committed)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    brightdata_api_key: str = os.getenv("BRIGHTDATA_API_KEY", "")
    brightdata_unlocker_zone: str = os.getenv("BRIGHTDATA_UNLOCKER_ZONE", "mcp_unlocker")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-6-luna")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    falkordb_host: str = os.getenv("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(os.getenv("FALKORDB_PORT", "6379"))
    falkordb_username: str | None = os.getenv("FALKORDB_USERNAME") or None
    falkordb_password: str | None = os.getenv("FALKORDB_PASSWORD") or None
    falkordb_tls: bool = os.getenv("FALKORDB_TLS", "false").lower() == "true"
    graph_name: str = os.getenv("CAPY_GRAPH", "capy")
    data_dir: Path = ROOT / "data"


settings = Settings()
