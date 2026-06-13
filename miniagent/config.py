"""Configuration management."""

import json
import os
from pathlib import Path
from typing import Any

# Auto-load .env file from project root
try:
    from dotenv import load_dotenv
    _project_root = Path(__file__).resolve().parent.parent
    _env_file = _project_root / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
except ImportError:
    pass


DEFAULT_CONFIG = {
    "model": "qwen-plus",
    "api_key": "",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "temperature": 0.7,
    "max_tokens": 32768,
    "max_history": 20,
    "system_prompt": "你是一个有帮助的 AI 助手。请用中文回答问题。",
    "skills_dir": None,
}


def get_app_dir() -> Path:
    """Return the MiniAgent application directory (~/.miniagent)."""
    app_dir = Path.home() / ".miniagent"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_config_path() -> Path:
    """Return the config file path."""
    return get_app_dir() / "config.json"


def load_config(project_config: Path | None = None) -> dict[str, Any]:
    """Load configuration with cascading priority:

    1. Project-level config.json (highest)
    2. User-level ~/.miniagent/config.json
    3. Environment variables
    4. Defaults (lowest)
    """
    config = dict(DEFAULT_CONFIG)

    # User-level config
    user_config = get_config_path()
    if user_config.exists():
        with open(user_config, "r", encoding="utf-8") as f:
            user_data = json.load(f)

        # Auto-upgrade: if saved max_tokens is below the current default, bump it
        saved_tokens = user_data.get("max_tokens", None)
        if saved_tokens is not None and saved_tokens < DEFAULT_CONFIG["max_tokens"]:
            import logging
            logging.getLogger("miniagent").info(
                f"[config] Auto-upgrading max_tokens: {saved_tokens} -> {DEFAULT_CONFIG['max_tokens']}"
            )
            user_data["max_tokens"] = DEFAULT_CONFIG["max_tokens"]

        config.update(user_data)

    # Project-level config
    if project_config and project_config.exists():
        with open(project_config, "r", encoding="utf-8") as f:
            proj_data = json.load(f)
        config.update(proj_data)

    # Environment variables
    env_key = os.environ.get("DASHSCOPE_API_KEY")
    if env_key:
        config["api_key"] = env_key

    env_base = os.environ.get("DASHSCOPE_BASE_URL")
    if env_base:
        config["base_url"] = env_base

    env_model = os.environ.get("MINIAGENT_MODEL")
    if env_model:
        config["model"] = env_model

    return config


def get_skills_dir(config: dict[str, Any]) -> Path:
    """Return the skills directory path."""
    if config.get("skills_dir"):
        return Path(config["skills_dir"]).expanduser()
    return get_app_dir() / "skills"


def save_config(config: dict[str, Any]) -> Path:
    """Save configuration to user-level config file."""
    path = get_config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    return path
