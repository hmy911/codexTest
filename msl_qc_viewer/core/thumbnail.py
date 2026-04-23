from __future__ import annotations

import base64
import tkinter as tk
from pathlib import Path

from .utils import is_previewable_image, is_tk_builtin_image, path_to_file_uri


STATUS_COLORS = {
    "OK": "#2d8f5b",
    "WARN": "#b8871f",
    "FAIL": "#b94a48",
    "INFO": "#516b8f",
}

try:
    from PIL import Image, ImageTk  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Image = None
    ImageTk = None

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None

try:
    import OpenImageIO as oiio
except Exception:  # pragma: no cover - optional dependency
    oiio = None


def _placeholder_svg(label: str, status: str, width: int, height: int) -> str:
    safe_label = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    color = STATUS_COLORS.get(status, STATUS_COLORS["INFO"])
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>"
        f"<rect width='{width}' height='{height}' rx='8' fill='#1a1f25'/>"
        f"<rect x='4' y='4' width='{width - 8}' height='{height - 8}' rx='6' fill='{color}' opacity='0.24'/>"
        f"<text x='50%' y='46%' text-anchor='middle' fill='#f5f7fa' font-size='14' font-family='Segoe UI, Arial'>{safe_label}</text>"
        f"<text x='50%' y='67%' text-anchor='middle' fill='#c7d0d9' font-size='11' font-family='Segoe UI, Arial'>{status}</text>"
        "</svg>"
    )


def placeholder_data_uri(label: str, status: str, width: int = 180, height: int = 102) -> str:
    svg = _placeholder_svg(label, status, width, height)
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def create_placeholder_photo(label: str, status: str, width: int = 120, height: int = 68) -> tk.PhotoImage:
    color = STATUS_COLORS.get(status, STATUS_COLORS["INFO"])
    image = tk.PhotoImage(width=width, height=height)
    image.put("#1a1f25", to=(0, 0, width, height))
    image.put(color, to=(4, 4, width - 4, height - 4))
    image.put("#1a1f25", to=(8, 8, width - 8, height - 8))
    return image


def _load_pixels_with_oiio(path: Path, max_size: tuple[int, int]) -> object | None:
    if oiio is None or np is None:
        return None

    try:
        image = oiio.ImageBuf(str(path))
        if not image.initialized:
            return None

        spec = image.spec()
        width = max(1, int(spec.width))
        height = max(1, int(spec.height))
        max_width, max_height = max_size
        scale = min(max_width / width, max_height / height, 1.0)
        target_width = max(1, int(round(width * scale)))
        target_height = max(1, int(round(height * scale)))

        if target_width != width or target_height != height:
            roi = oiio.ROI(0, target_width, 0, target_height, 0, 1, 0, spec.nchannels)
            image = oiio.ImageBufAlgo.resize(image, roi=roi)

        pixels = image.get_pixels(oiio.FLOAT)
        if pixels is None:
            return None
        return np.asarray(pixels, dtype=np.float32)
    except Exception:
        return None


def _rgb_array_from_pixels(pixels: object) -> object | None:
    if np is None:
        return None

    array = np.asarray(pixels)
    if array.size == 0:
        return None

    if array.ndim == 2:
        array = np.repeat(array[:, :, None], 3, axis=2)
    elif array.ndim == 3 and array.shape[2] == 1:
        array = np.repeat(array, 3, axis=2)
    elif array.ndim == 3 and array.shape[2] >= 3:
        array = array[:, :, :3]
    else:
        return None

    return array


def _tone_map_uint8(rgb: object) -> object | None:
    if np is None:
        return None

    image = np.asarray(rgb, dtype=np.float32)
    image = np.nan_to_num(image, nan=0.0, posinf=0.0, neginf=0.0)
    image = np.maximum(image, 0.0)

    positive = image[image > 0.0]
    if positive.size:
        white = float(np.percentile(positive, 99.0))
        if white <= 0.0:
            white = float(positive.max())
    else:
        white = 1.0

    white = max(white, 1.0e-6)
    image = np.clip(image / white, 0.0, 1.0)
    image = np.power(image, 1.0 / 2.2)
    return (image * 255.0 + 0.5).astype(np.uint8)


def _ppm_bytes_from_rgb(rgb: object) -> bytes | None:
    if np is None:
        return None

    image = np.asarray(rgb, dtype=np.uint8)
    if image.ndim != 3 or image.shape[2] != 3:
        return None

    height, width = image.shape[:2]
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    return header + image.tobytes()


def _bmp_bytes_from_rgb(rgb: object) -> bytes | None:
    if np is None:
        return None

    image = np.asarray(rgb, dtype=np.uint8)
    if image.ndim != 3 or image.shape[2] != 3:
        return None

    height, width = image.shape[:2]
    row_stride = width * 3
    row_padding = (4 - (row_stride % 4)) % 4
    pixel_rows = []
    for row in image[::-1]:
        bgr = row[:, ::-1].tobytes()
        pixel_rows.append(bgr + (b"\x00" * row_padding))

    pixel_data = b"".join(pixel_rows)
    file_size = 14 + 40 + len(pixel_data)
    header = bytearray()
    header.extend(b"BM")
    header.extend(file_size.to_bytes(4, "little"))
    header.extend((0).to_bytes(4, "little"))
    header.extend((54).to_bytes(4, "little"))
    header.extend((40).to_bytes(4, "little"))
    header.extend(width.to_bytes(4, "little", signed=True))
    header.extend(height.to_bytes(4, "little", signed=True))
    header.extend((1).to_bytes(2, "little"))
    header.extend((24).to_bytes(2, "little"))
    header.extend((0).to_bytes(4, "little"))
    header.extend(len(pixel_data).to_bytes(4, "little"))
    header.extend((2835).to_bytes(4, "little", signed=True))
    header.extend((2835).to_bytes(4, "little", signed=True))
    header.extend((0).to_bytes(4, "little"))
    header.extend((0).to_bytes(4, "little"))
    return bytes(header) + pixel_data


def _photo_from_rgb(rgb: object) -> tk.PhotoImage | None:
    ppm = _ppm_bytes_from_rgb(rgb)
    if ppm is None:
        return None
    return tk.PhotoImage(data=ppm, format="PPM")


def create_tk_thumbnail(path: Path | None, status: str, label: str, max_size: tuple[int, int] = (120, 68)) -> tk.PhotoImage:
    width, height = max_size
    if path is None:
        return create_placeholder_photo(label, status, width, height)

    if Image is not None and ImageTk is not None:
        try:
            with Image.open(path) as source:
                image = source.convert("RGB")
                image.thumbnail(max_size)
                return ImageTk.PhotoImage(image)
        except Exception:
            pass

    pixels = _load_pixels_with_oiio(path, max_size)
    if pixels is not None:
        rgb = _rgb_array_from_pixels(pixels)
        if rgb is not None:
            tonemapped = _tone_map_uint8(rgb)
            if tonemapped is not None:
                photo = _photo_from_rgb(tonemapped)
                if photo is not None:
                    return photo

    if is_tk_builtin_image(path):
        try:
            image = tk.PhotoImage(file=str(path))
            scale = max(1, (max(image.width() / width, image.height() / height)))
            if scale > 1:
                image = image.subsample(int(scale) if scale.is_integer() else int(scale) + 1)
            return image
        except Exception:
            pass

    return create_placeholder_photo(label, status, width, height)


def thumbnail_src_for_html(path: Path | None, status: str, label: str, size: tuple[int, int] = (240, 135)) -> str:
    width, height = size
    if path is None:
        return placeholder_data_uri(label, status, width, height)

    pixels = _load_pixels_with_oiio(path, size)
    if pixels is not None:
        rgb = _rgb_array_from_pixels(pixels)
        if rgb is not None:
            tonemapped = _tone_map_uint8(rgb)
            if tonemapped is not None:
                bmp = _bmp_bytes_from_rgb(tonemapped)
                if bmp is not None:
                    encoded = base64.b64encode(bmp).decode("ascii")
                    return f"data:image/bmp;base64,{encoded}"

    if Image is not None:
        try:
            from io import BytesIO

            with Image.open(path) as source:
                image = source.convert("RGB")
                image.thumbnail(size)
                buffer = BytesIO()
                image.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            return f"data:image/png;base64,{encoded}"
        except Exception:
            pass

    if is_previewable_image(path):
        return path_to_file_uri(path)

    return placeholder_data_uri(label, status, width, height)
