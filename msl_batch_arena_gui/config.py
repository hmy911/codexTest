import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


APP_NAME = "MSL_batch_Arena_GUI"
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
CONFIG_FILENAME = "msl_batch_arena_gui_config.json"


@dataclass
class AppConfig:
    mayapy_path: str = r"C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe"
    project_root: str = r"D:\codex"
    source_scripts_root: str = r"D:\codex\MSL_batch_Arena"
    step1_path: str = r"D:\codex\MSL_batch_Arena\step1_export_shot.py"
    step2_path: str = r"D:\codex\MSL_batch_Arena\step2_build_arena.py"
    step3_path: str = r"D:\codex\MSL_batch_Arena\step3_submit_deadline.py"
    arena_scene: str = ""
    version_note: str = ""
    extra_step1_args: str = ""
    extra_step2_args: str = ""
    extra_step3_args: str = ""


def resource_path(*parts: str) -> Path:
    return PACKAGE_DIR.joinpath(*parts)


def _default_local_config_dir() -> Path:
    appdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / "AppData" / "Local" / APP_NAME


def config_candidates() -> list[Path]:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        return [
            exe_dir / CONFIG_FILENAME,
            _default_local_config_dir() / CONFIG_FILENAME,
        ]
    return [PROJECT_DIR / CONFIG_FILENAME]


def active_config_path() -> Path:
    candidates = config_candidates()
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_config() -> AppConfig:
    config_path = active_config_path()
    if not config_path.exists():
        return AppConfig()

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return AppConfig()

    defaults = asdict(AppConfig())
    defaults.update({key: value for key, value in raw.items() if key in defaults})
    return AppConfig(**defaults)


def save_config(config: AppConfig) -> Path:
    payload = json.dumps(asdict(config), indent=2, ensure_ascii=False)
    last_error: OSError | None = None

    for config_path in config_candidates():
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(payload, encoding="utf-8")
            return config_path
        except OSError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error

    raise OSError("No writable config path is available.")
