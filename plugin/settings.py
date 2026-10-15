"""Portable settings with no third-party dependencies."""
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tomllib


@dataclass
class Settings:
    herdr_binary: str = "herdr"
    socket_path: str = ""
    pi_sessions: str = ""
    pi_titles: bool = True
    kimi_compat: bool = False


def load_settings():
    path = Path(os.environ.get("HERDR_SIDEBAR_CONFIG", Path(__file__).with_name("settings.toml")))
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    unknown = set(data) - set(Settings.__dataclass_fields__)
    if unknown:
        raise ValueError("Unknown sidebar settings: " + ", ".join(sorted(unknown)))
    settings = Settings(**data)
    settings.herdr_binary = settings.herdr_binary or shutil.which("herdr") or "herdr"
    settings.socket_path = str(Path(settings.socket_path or Path.home() / ".config/herdr/herdr.sock").expanduser())
    settings.pi_sessions = str(Path(settings.pi_sessions or Path.home() / ".pi/agent/sessions").expanduser())
    return settings
