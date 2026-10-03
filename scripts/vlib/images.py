#!/usr/bin/env python3
# Crop from the oriented original, not from an already resized overview.
import io
import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from PIL import Image, ImageCms, ImageEnhance, ImageOps

RAW_SUFFIXES = (".arw", ".dng", ".cr2", ".nef", ".raf", ".rw2", ".orf", ".srw", ".pef")
PILLOW_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".ppm")


@dataclass
class Variant:
    name: str
    box: tuple = (0.0, 0.0, 1.0, 1.0)
    long_edge: int = 0
    scale: float = 1.0
    contrast: float = 1.0
    sharpen: float = 1.0
    quality: int = 90


PRESETS = {
    "full": [Variant("full_1568", long_edge=1568), Variant("full_2048", long_edge=2048), Variant("full_native")],
    "provider": [Variant("full_1568", long_edge=1568), Variant("full_2048", long_edge=2048)],
    "quads": [Variant("quad_tl", (0, 0, 0.5, 0.5)), Variant("quad_tr", (0.5, 0, 1, 0.5)), Variant("quad_bl", (0, 0.5, 0.5, 1)), Variant("quad_br", (0.5, 0.5, 1, 1))],
    "bands": [Variant("band_top", (0, 0, 1, 0.4)), Variant("band_mid", (0, 0.3, 1, 0.7)), Variant("band_bot", (0, 0.6, 1, 1))],
    "centre": [Variant("centre_2x", (0.25, 0.2, 0.85, 0.8), scale=2.0, contrast=1.1, sharpen=1.2)],
    "auto": [
        Variant("full_1568", long_edge=1568),
        Variant("full_2048", long_edge=2048),
        Variant("quad_tl", (0, 0, 0.5, 0.5)),
        Variant("quad_tr", (0.5, 0, 1, 0.5)),
        Variant("quad_bl", (0, 0.5, 0.5, 1)),
        Variant("quad_br", (0.5, 0.5, 1, 1)),
    ],
}

EXIF_KEYS = {
    271: "make",
    272: "model",
    42036: "lens",
    33437: "f_number",
    33434: "exposure",
    34855: "iso",
    37386: "focal_length",
    36867: "date_taken",
    306: "date_modified",
    274: "orientation",
    37377: "shutter_apex",
    37378: "aperture",
}


def _rational(value):
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return str(value)


def _gps_decimal(coord, ref):
    try:
        degrees, minutes, seconds = [float(x) for x in coord]
    except (TypeError, ValueError, IndexError):
        return None
    value = degrees + minutes / 60 + seconds / 3600
    if str(ref).upper() in ("S", "W"):
        value = -value
    return round(value, 6)


def open_image(path):
    path = Path(path)
    if not path.is_file():
        raise SystemExit(f"cannot read {path}: no such file")
    if path.stat().st_size == 0:
        raise SystemExit(f"cannot read {path.name}: the file is empty")
    if path.suffix.lower() in RAW_SUFFIXES:
        return _open_raw(path)
    try:
        return Image.open(path)
    except Exception:
        pass
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:
        if path.suffix.lower() in PILLOW_SUFFIXES:
            raise SystemExit(f"cannot read {path.name}: Pillow could not decode it, so the file is " "damaged or not really an image.")
        raise SystemExit(f'cannot read {path.name}: Pillow has no reader for {path.suffix or "this format"}. ' "For HEIC/AVIF install pillow-heif; otherwise convert the file to JPEG or PNG.")
    try:
        return Image.open(path)
    except Exception as exc:
        raise SystemExit(f"cannot read {path.name}: {exc}")


def _open_raw(path):
    try:
        import rawpy
    except ImportError:
        raise SystemExit(f"cannot read {path.name}: it is a raw file and rawpy is not installed. " "Install rawpy, or export a JPEG/PNG from the raw first.")
    # A raw thumbnail is not the original resolution needed for detail crops.
    with rawpy.imread(str(path)) as raw:
        return Image.fromarray(raw.postprocess(use_camera_wb=True)).convert("RGB")


def display_image(path):
    with open_image(path) as original:
        if getattr(original, "n_frames", 1) != 1:
            raise ValueError("animated or multipage images need explicit frame/page extraction first")
        image = ImageOps.exif_transpose(original)
        profile = original.info.get("icc_profile")
        alpha = image.convert("RGBA").getchannel("A") if ("A" in image.getbands() or "transparency" in image.info) else None
        if profile:
            source = image if image.mode in ("RGB", "CMYK", "LAB") else image.convert("RGB")
            image = ImageCms.profileToProfile(source, ImageCms.ImageCmsProfile(io.BytesIO(profile)), ImageCms.createProfile("sRGB"), outputMode="RGB")
        else:
            image = image.convert("RGB")
        if alpha is not None:
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=alpha)
            image = background
        image.load()
        image.info.clear()
        return image


def upload_bytes(path):
    if Path(path).suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        raise ValueError("send JPEG/PNG/WebP or a still GIF; use prep for raw, TIFF or HEIC input")
    with display_image(path) as image:
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return "image/png", buffer.getvalue()


def probe(path):
    path = Path(path)
    with open_image(path) as image:
        width, height = image.size
        if image.getexif().get(274) in (5, 6, 7, 8):
            width, height = height, width
        return {
            "path": str(path),
            "name": path.name,
            "format": image.format,
            "width": width,
            "height": height,
            "long_edge": max(width, height),
            "megapixels": round(width * height / 1e6, 2),
            "bytes": path.stat().st_size,
            "frames": getattr(image, "n_frames", 1),
            "exif": exif_summary(image),
        }


def exif_summary(image):
    out = {}
    try:
        exif = image.getexif()
    except Exception:
        return out
    if not exif:
        return out
    for key, name in EXIF_KEYS.items():
        if key in exif and exif[key] not in (None, ""):
            out[name] = _rational(exif[key])
    try:
        sub = exif.get_ifd(0x8769)
    except Exception:
        sub = {}
    if 36867 in sub:
        out["date_taken"] = str(sub[36867])
    if 33434 in sub and "exposure" not in out:
        out["exposure"] = str(sub[33434])
    if 33437 in sub and "f_number" not in out:
        out["f_number"] = _rational(sub[33437])
    if 34855 in sub and "iso" not in out:
        out["iso"] = _rational(sub[34855])
    if 37386 in sub and "focal_length" not in out:
        out["focal_length"] = _rational(sub[37386])
    try:
        gps = exif.get_ifd(0x8825)
    except Exception:
        gps = {}
    if gps and 2 in gps and 1 in gps:
        lat = _gps_decimal(gps.get(2), gps.get(1))
        lon = _gps_decimal(gps.get(4), gps.get(3))
        if lat is not None and lon is not None:
            out["gps"] = {"lat": lat, "lon": lon}
    return out


def crop_box(fractions, width, height):
    left, top, right, bottom = fractions
    box = (int(left * width), int(top * height), int(right * width), int(bottom * height))
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("crop is smaller than one source pixel")
    return box


def render(image, variant, max_long_edge=0):
    left, top, right, bottom = variant.box
    if (left, top, right, bottom) != (0.0, 0.0, 1.0, 1.0):
        image = image.crop(crop_box(variant.box, image.width, image.height))
    if variant.long_edge and max(image.size) > variant.long_edge:
        factor = variant.long_edge / max(image.size)
        image = image.resize((max(1, round(image.width * factor)), max(1, round(image.height * factor))), Image.LANCZOS)
    if variant.scale != 1.0:
        image = image.resize((max(1, round(image.width * variant.scale)), max(1, round(image.height * variant.scale))), Image.LANCZOS)
    if variant.contrast != 1.0:
        image = ImageEnhance.Contrast(image).enhance(variant.contrast)
    if variant.sharpen != 1.0:
        image = ImageEnhance.Sharpness(image).enhance(variant.sharpen)
    if max_long_edge and max(image.size) > max_long_edge:
        factor = max_long_edge / max(image.size)
        image = image.resize((max(1, round(image.width * factor)), max(1, round(image.height * factor))), Image.LANCZOS)
    return image.convert("RGB")


def save(image, path, quality=90):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        image.save(handle, "JPEG", quality=int(quality), optimize=True)
    return {"path": str(path), "width": image.width, "height": image.height, "bytes": path.stat().st_size, "kilobytes": round(path.stat().st_size / 1024, 1)}


def prepare(src, out_dir, variants, max_long_edge=0, quality=None, prefix="", manifest=None):
    src = Path(src)
    out_dir = Path(out_dir)
    if max_long_edge < 0:
        raise ValueError("--max-long-edge must be nonnegative")
    for text in [prefix] + [v.name for v in variants]:
        if "/" in text or "\\" in text:
            raise ValueError("prefix and variant name must not contain path separators")
    targets = [out_dir / f"{prefix}{src.stem}_{v.name}.jpg" for v in variants]
    if len(set(targets)) != len(targets) or any(p.exists() or p.resolve() == src.resolve() for p in targets):
        raise ValueError("prep would overwrite a source or output; choose a new --out or --prefix")
    results = []
    with display_image(src) as image:
        for variant, target in zip(variants, targets):
            with render(image, variant, max_long_edge=max_long_edge) as rendered:
                saved = save(rendered, target, quality=quality if quality is not None else variant.quality)
            saved.update(
                {
                    "variant": variant.name,
                    "box": list(variant.box),
                    "source": str(src.resolve()),
                    "source_size": list(image.size),
                    "box_pixels": list(crop_box(variant.box, *image.size)),
                    "transform": asdict(variant),
                    "max_long_edge": max_long_edge,
                }
            )
            results.append(saved)
    if manifest:
        Path(manifest).parent.mkdir(parents=True, exist_ok=True)
        Path(manifest).write_text(json.dumps({"source": str(src), "variants": results}, indent=2))
    return results


def parse_box(text):
    if isinstance(text, (list, tuple)):
        box = tuple(float(x) for x in text)
    else:
        parts = [float(x) for x in text.replace(":", ",").split(",")]
        box = tuple(parts)
    if len(box) != 4 or not all(0.0 <= v <= 1.0 for v in box):
        raise SystemExit("--box needs four comma-separated fractions between 0 and 1: " "left,top,right,bottom")
    left, top, right, bottom = box
    if right <= left or bottom <= top:
        raise SystemExit(f"--box {text} is empty: right must exceed left and bottom must exceed top")
    return box


def custom_variants(box=None, long_edge=0, scale=1.0, contrast=1.0, sharpen=1.0, quality=90, name=None):
    spec = Variant(name or ("crop" if box else "full"), box=parse_box(box) if box else (0.0, 0.0, 1.0, 1.0), long_edge=long_edge, scale=scale, contrast=contrast, sharpen=sharpen, quality=quality)
    return [spec]


def variant_list(preset, box=None, long_edge=0, scale=1.0, contrast=1.0, sharpen=1.0, quality=90, name=None):
    if long_edge < 0 or not 1 <= quality <= 100:
        raise ValueError("long edge must be nonnegative; JPEG quality must be 1 to 100")
    if not all(math.isfinite(v) and v > 0 for v in (scale, contrast, sharpen)):
        raise ValueError("scale, contrast and sharpen must be finite and positive")
    if box or long_edge or scale != 1.0 or contrast != 1.0 or sharpen != 1.0 or name:
        return custom_variants(box, long_edge, scale, contrast, sharpen, quality, name)
    if preset not in PRESETS:
        raise SystemExit(f'unknown preset {preset!r}; choose from {", ".join(PRESETS)}')
    return [replace(v, quality=quality) for v in PRESETS[preset]]
