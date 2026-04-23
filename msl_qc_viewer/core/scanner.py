from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .utils import (
    build_lighting_dir,
    find_latest_version_dir,
    gather_image_files,
    is_crypto_file,
    pick_best_image,
    sequence_from_shotcode,
)


@dataclass(slots=True)
class ScanResult:
    shotcode: str
    sequence: str | None
    lighting_dir: Path | None
    latest_version_dir: Path | None
    representative_image: Path | None
    thumbnail_source: Path | None
    status: str
    message: str
    beauty_found: bool
    crypto_found: bool
    image_count: int


def scan_shotcodes(project_root: str | Path, shotcodes: list[str]) -> list[ScanResult]:
    return [scan_shotcode(project_root, shotcode) for shotcode in shotcodes]


def scan_shotcode(project_root: str | Path, shotcode: str) -> ScanResult:
    sequence = sequence_from_shotcode(shotcode)
    if sequence is None:
        return ScanResult(
            shotcode=shotcode,
            sequence=None,
            lighting_dir=None,
            latest_version_dir=None,
            representative_image=None,
            thumbnail_source=None,
            status="FAIL",
            message="Invalid shotcode format. Expected at least three '_' parts.",
            beauty_found=False,
            crypto_found=False,
            image_count=0,
        )

    lighting_dir = build_lighting_dir(project_root, shotcode)
    assert lighting_dir is not None

    if not lighting_dir.exists():
        return ScanResult(
            shotcode=shotcode,
            sequence=sequence,
            lighting_dir=lighting_dir,
            latest_version_dir=None,
            representative_image=None,
            thumbnail_source=None,
            status="FAIL",
            message="Lighting directory is missing.",
            beauty_found=False,
            crypto_found=False,
            image_count=0,
        )

    latest_version_dir = find_latest_version_dir(lighting_dir)
    if latest_version_dir is None:
        return ScanResult(
            shotcode=shotcode,
            sequence=sequence,
            lighting_dir=lighting_dir,
            latest_version_dir=None,
            representative_image=None,
            thumbnail_source=None,
            status="FAIL",
            message="No version folder found under lighting.",
            beauty_found=False,
            crypto_found=False,
            image_count=0,
        )

    image_files = gather_image_files(latest_version_dir)
    if not image_files:
        return ScanResult(
            shotcode=shotcode,
            sequence=sequence,
            lighting_dir=lighting_dir,
            latest_version_dir=latest_version_dir,
            representative_image=None,
            thumbnail_source=None,
            status="FAIL",
            message="Latest version exists, but no image files were found.",
            beauty_found=False,
            crypto_found=False,
            image_count=0,
        )

    beauty_files = [path for path in image_files if not is_crypto_file(path)]
    crypto_files = [path for path in image_files if is_crypto_file(path)]
    beauty_found = bool(beauty_files)
    crypto_found = bool(crypto_files)

    if beauty_found and crypto_found:
        status = "OK"
        message = f"Beauty and crypto found ({len(image_files)} image files)."
    elif beauty_found:
        status = "WARN"
        message = "Beauty found, but crypto is missing."
    elif crypto_found:
        status = "FAIL"
        message = "Crypto found, but no beauty render was detected."
    else:
        status = "FAIL"
        message = "Images found, but no beauty or crypto render was detected."

    representative_image = pick_best_image(beauty_files) or pick_best_image(image_files)
    thumbnail_source = representative_image

    return ScanResult(
        shotcode=shotcode,
        sequence=sequence,
        lighting_dir=lighting_dir,
        latest_version_dir=latest_version_dir,
        representative_image=representative_image,
        thumbnail_source=thumbnail_source,
        status=status,
        message=message,
        beauty_found=beauty_found,
        crypto_found=crypto_found,
        image_count=len(image_files),
    )
