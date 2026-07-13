"""Paths, env loading, and the model registry."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("COMMUNITY_DB", REPO_ROOT / "data" / "community.sqlite"))
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

EMBEDDING_MODEL = "voyage-3-large"
EMBEDDING_DIM = 1024
DEFAULT_COMMUNITY = "games"  # lemmy community name
USER_AGENT = "community-voices/0.1 (take-home demo; contact: repo issues)"


def _load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    # ponytail: 10-line stdlib .env parser instead of a python-dotenv dep
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# Generation model registry, DeepSeek V4 first (zero-key demo default).
# Prices are USD per million tokens (input, output) for the cost estimates
# shown in comparisons; update if a vendor changes them.
MODELS: dict[str, dict] = {
    "deepseek-v4": {
        "provider": "openai_compat",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
        "label": "DeepSeek V4",
        "vendor": "DeepSeek",
        "price_in": 0.28,
        "price_out": 0.42,
    },
    "deepseek-v4-flash": {
        "provider": "openai_compat",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
        "label": "DeepSeek V4 Flash",
        "vendor": "DeepSeek",
        "price_in": 0.14,
        "price_out": 0.28,
    },
    "claude-opus-4-8": {
        "provider": "anthropic",
        "model": "claude-opus-4-8",
        "key_env": "ANTHROPIC_API_KEY",
        "label": "Claude Opus 4.8",
        "vendor": "Anthropic",
        "price_in": 5.00,
        "price_out": 25.00,
    },
    "claude-sonnet-5": {
        "provider": "anthropic",
        "model": "claude-sonnet-5",
        "key_env": "ANTHROPIC_API_KEY",
        "label": "Claude Sonnet 5",
        "vendor": "Anthropic",
        "price_in": 3.00,
        "price_out": 15.00,
    },
}

DEFAULT_MODEL_KEY = "deepseek-v4"

# Switchable ingest sources for the sidebar source picker — each reuses the
# shared crawl/chunk/embed pipeline in app.ingest.
SOURCES: list[dict] = [
    {"key": "lemmy:games", "kind": "lemmy", "community": "games", "label": "c/games (Lemmy)"},
    {"key": "lemmy:technology", "kind": "lemmy", "community": "technology", "label": "c/technology (Lemmy)"},
    {"key": "lemmy:asklemmy", "kind": "lemmy", "community": "asklemmy", "label": "c/asklemmy (Lemmy)"},
    {"key": "hackernews", "kind": "hackernews", "label": "Hacker News"},
]


def available_models() -> list[str]:
    """Model keys whose API key is present in the environment."""
    return [key for key, cfg in MODELS.items() if os.environ.get(cfg["key_env"])]
