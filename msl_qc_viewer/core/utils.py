from __future__ import annotations

import html
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


IMAGE_FILE_SUFFIXES = {".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".iff"}
PREVIEWABLE_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
TK_BUILTIN_IMAGE_SUFFIXES = {".png", ".gif", ".ppm", ".pgm"}
VERSION_RE = re.compile(r"^v(\d+)", re.IGNORECASE)
CRYPTO_KEYWORDS = ("crypto", "cryptomatte")
BEAUTY_HINTS = ("beauty", "rgba", "rgb", "render", "final", "main")


def parse_shotcodes(raw_text: str) -> list[str]:
    tokens: list[str] = []
    for line in raw_text.replace(",", " ").splitlines():
        tokens.extend(piece.strip() for piece in line.split())
    return [token for token in tokens if token]


def sequence_from_shotcode(shotcode: str) -> str | None:
    parts = shotcode.split("_")
    if len(parts) < 3:
        return None
    return parts[1]


def build_lighting_dir(project_root: str | Path, shotcode: str) -> Path | None:
    seq = sequence_from_shotcode(shotcode)
    if seq is None:
        return None
    return Path(project_root) / "shots" / seq / shotcode / "images" / "3d_renders" / "lighting"


def find_latest_version_dir(base_dir: Path) -> Path | None:
    if not base_dir.exists():
        return None

    candidates: list[tuple[int, Path]] = []
    for path in base_dir.iterdir():
        if not path.is_dir():
            continue
        match = VERSION_RE.match(path.name)
        if match:
            candidates.append((int(match.group(1)), path))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1].name.lower()))
    return candidates[-1][1]


def gather_image_files(base_dir: Path) -> list[Path]:
    if not base_dir.exists():
        return []
    return [
        path for path in base_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_FILE_SUFFIXES
    ]


def is_crypto_file(path: Path) -> bool:
    lowered = str(path).lower()
    return any(keyword in lowered for keyword in CRYPTO_KEYWORDS)


def is_previewable_image(path: Path) -> bool:
    return path.suffix.lower() in PREVIEWABLE_IMAGE_SUFFIXES


def is_tk_builtin_image(path: Path) -> bool:
    return path.suffix.lower() in TK_BUILTIN_IMAGE_SUFFIXES


def score_candidate(path: Path) -> tuple[int, int, float, str]:
    lowered = str(path).lower()
    hint_score = 1 if any(keyword in lowered for keyword in BEAUTY_HINTS) else 0
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (hint_score, 1 if is_previewable_image(path) else 0, mtime, lowered)


def pick_best_image(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    return max(paths, key=score_candidate)


def html_escape(value: str) -> str:
    return html.escape(value, quote=True)


def path_to_file_uri(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().as_uri()
    except ValueError:
        return f"file:///{quote(str(path.resolve()).replace(os.sep, '/'))}"


def open_in_file_browser(target: Path | None) -> None:
    if target is None:
        return

    target = target.resolve()
    if sys.platform.startswith("win"):
        os.startfile(str(target if target.is_dir() else target.parent))
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(target if target.is_dir() else target.parent)])
        return
    subprocess.Popen(["xdg-open", str(target if target.is_dir() else target.parent)])


def open_with_default_app(target: Path | None) -> None:
    if target is None:
        return

    target = target.resolve()
    if sys.platform.startswith("win"):
        os.startfile(str(target))
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
        return
    subprocess.Popen(["xdg-open", str(target)])
