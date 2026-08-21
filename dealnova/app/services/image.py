# dealnova/app/services/image.py
import os
import shutil
import subprocess
import uuid
from werkzeug.utils import secure_filename
from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import pillow_avif  # type: ignore  # Registers AVIF support in Pillow when installed.
except Exception:
    pillow_avif = None

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif", "jfif", "bmp", "tif", "tiff", "avif", "heic", "heif"}
VIDEO_EXTENSIONS = {"mp4", "mov", "webm", "m4v", "avi", "mkv", "3gp", "mpeg", "mpg", "wmv", "flv"}
THUMB_SIZE = 300
LARGE_SIZE = 900
MAX_PRODUCT_VIDEO_BYTES = 30 * 1024 * 1024

# Qualite elevee pour garder un beau rendu
MAIN_WEBP_QUALITY = 90
VARIANT_WEBP_QUALITY = 86
WEBP_METHOD = 6


def allowed_file(filename: str) -> bool:
    if "." not in (filename or ""):
        return True
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def allowed_video_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in VIDEO_EXTENSIONS


def _variant_name(filename: str, size: int) -> str:
    base, _ = os.path.splitext(filename)
    return f"{base}_{size}.webp"


def _main_webp_name(filename: str) -> str:
    base, _ = os.path.splitext(filename)
    return f"{base}.webp"


def _is_animated_image(img: Image.Image) -> bool:
    try:
        return bool(getattr(img, "is_animated", False) or getattr(img, "n_frames", 1) > 1)
    except Exception:
        return False


def _normalize_image(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)

    # WEBP gere bien RGB / RGBA ; on normalise les autres modes
    if img.mode not in ("RGB", "RGBA"):
        if "A" in img.getbands():
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")

    try:
        img.info.clear()
    except Exception:
        pass

    return img


def _save_webp(img: Image.Image, path: str, *, quality: int) -> None:
    save_kwargs = {
        "format": "WEBP",
        "quality": quality,
        "method": WEBP_METHOD,
    }

    # Sans perte si image tres simple avec transparence ? Non:
    # on reste en qualite elevee pour garder la beaute visuelle.
    img.save(path, **save_kwargs)


def _save_variant(img: Image.Image, path: str, size: int, crop_square: bool) -> None:
    if crop_square:
        variant = ImageOps.fit(
            img,
            (size, size),
            method=Image.LANCZOS,
            centering=(0.5, 0.5),
        )
    else:
        variant = img.copy()
        variant.thumbnail((size, size), Image.LANCZOS)

    _save_webp(variant, path, quality=VARIANT_WEBP_QUALITY)


def _file_size(file_storage) -> int:
    stream = getattr(file_storage, "stream", None)
    if not stream:
        return 0
    try:
        current = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = int(stream.tell() or 0)
        stream.seek(current)
        return size
    except Exception:
        return 0


def _uploads_root_dir() -> str:
    configured = str(current_app.config.get("UPLOAD_FOLDER") or "").strip()
    if configured:
        os.makedirs(configured, exist_ok=True)
        return configured

    fallback = os.path.join(current_app.static_folder, "uploads")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def _product_video_upload_dir() -> str:
    upload_dir = os.path.join(_uploads_root_dir(), "product_videos")
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _product_video_rel_path(filename: str) -> str:
    return f"uploads/product_videos/{filename}"


def _guess_image_extension(filename: str | None, content_type: str | None) -> str:
    if "." in (filename or ""):
        ext = str(filename).rsplit(".", 1)[-1].lower().strip()
        if ext:
            return ext

    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    mime_map = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
        "image/bmp": "bmp",
        "image/tiff": "tiff",
        "image/x-tiff": "tiff",
        "image/avif": "avif",
        "image/heic": "heic",
        "image/heif": "heif",
    }
    return mime_map.get(mime, "img")


def save_image(file_storage) -> str | None:
    """
    Sauvegarde une image dans: <app.static_folder>/uploads

    Nouveau comportement:
    - images classiques (jpg/png/jpeg/webp) -> enregistrement principal en .webp
    - variantes automatiques:
        * _300.webp
        * _900.webp
    - gif anime -> on conserve l'original pour ne pas casser l'animation

    Retourne uniquement le filename stocke (ex: abcd.webp ou abcd.gif)
    """
    if not file_storage or not file_storage.filename:
        return None

    filename = secure_filename(file_storage.filename)
    if not filename:
        filename = f"upload.{_guess_image_extension(getattr(file_storage, 'filename', ''), getattr(file_storage, 'content_type', ''))}"

    ext = _guess_image_extension(filename, getattr(file_storage, "content_type", ""))
    upload_dir = _uploads_root_dir()
    os.makedirs(upload_dir, exist_ok=True)

    original_uuid = uuid.uuid4().hex
    original_name = f"{original_uuid}.{ext}"
    original_path = os.path.join(upload_dir, original_name)

    try:
        # Revenir au debut du flux si possible
        stream = getattr(file_storage, "stream", None)
        if stream:
            try:
                stream.seek(0)
            except Exception:
                pass

        image_source = stream if stream else file_storage
        with Image.open(image_source) as img:
            # Cas special: GIF anime -> on garde l'original
            if ext == "gif" and _is_animated_image(img):
                try:
                    if stream:
                        stream.seek(0)
                except Exception:
                    pass

                file_storage.save(original_path)
                return original_name

            img = _normalize_image(img)

            # Nom principal stocke = .webp
            main_name = _main_webp_name(original_name)
            main_path = os.path.join(upload_dir, main_name)

            # Image principale compressee en WebP
            try:
                _save_webp(img, main_path, quality=MAIN_WEBP_QUALITY)
            except Exception:
                if os.path.exists(main_path):
                    try:
                        os.remove(main_path)
                    except Exception:
                        pass
                try:
                    if stream:
                        stream.seek(0)
                except Exception:
                    pass
                file_storage.save(original_path)
                return original_name

            # Variantes derivees depuis l'image normalisee
            thumb_path = os.path.join(upload_dir, _variant_name(main_name, THUMB_SIZE))
            large_path = os.path.join(upload_dir, _variant_name(main_name, LARGE_SIZE))
            _save_variant(img, thumb_path, THUMB_SIZE, crop_square=True)
            _save_variant(img, large_path, LARGE_SIZE, crop_square=False)

            return main_name

    except UnidentifiedImageError:
        current_app.logger.warning(
            "image.save_image.invalid_image",
            extra={
                "upload_filename": filename,
                "upload_content_type": getattr(file_storage, "content_type", None),
            },
        )
        return None
    except Exception:
        current_app.logger.exception(
            "image.save_image.failed",
            extra={
                "upload_filename": filename,
                "upload_content_type": getattr(file_storage, "content_type", None),
            },
        )
        return None


def image_variant(filename: str, size: str = "thumb") -> str:
    if not filename:
        return filename

    size_px = THUMB_SIZE if size in ("thumb", "small") else LARGE_SIZE
    variant = _variant_name(filename, size_px)
    upload_dir = _uploads_root_dir()

    if os.path.exists(os.path.join(upload_dir, variant)):
        return variant

    # Fallback de compatibilite pour anciens fichiers non-webp
    legacy_variant = _variant_name(filename, size_px)
    if os.path.exists(os.path.join(upload_dir, legacy_variant)):
        return legacy_variant

    return filename


def save_product_video(file_storage) -> str:
    if not file_storage or not file_storage.filename:
        raise ValueError("Aucune video fournie.")

    filename = secure_filename(file_storage.filename)
    if not filename or not allowed_video_file(filename):
        raise ValueError("Format video non supporte (mp4, mov, webm, m4v, avi).")

    size = _file_size(file_storage)
    if size and size > MAX_PRODUCT_VIDEO_BYTES:
        raise ValueError("Video trop lourde (max 30 MB).")

    ext = filename.rsplit(".", 1)[-1].lower()
    upload_dir = _product_video_upload_dir()
    base_name = uuid.uuid4().hex
    source_name = f"{base_name}.{ext}"
    source_path = os.path.join(upload_dir, source_name)

    try:
        stream = getattr(file_storage, "stream", None)
        if stream:
            try:
                stream.seek(0)
            except Exception:
                pass
        file_storage.save(source_path)

        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            try:
                os.remove(source_path)
            except Exception:
                pass
            raise ValueError("Validation video indisponible.")

        compressed_name = f"{base_name}.mp4"
        compressed_path = os.path.join(upload_dir, compressed_name)

        result = subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                source_path,
                "-vcodec",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "30",
                "-acodec",
                "aac",
                "-movflags",
                "+faststart",
                compressed_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

        if result.returncode == 0 and os.path.exists(compressed_path):
            compressed_size = os.path.getsize(compressed_path)
            if compressed_size <= MAX_PRODUCT_VIDEO_BYTES:
                try:
                    os.remove(source_path)
                except Exception:
                    pass
                return _product_video_rel_path(compressed_name)
            try:
                os.remove(compressed_path)
            except Exception:
                pass

        if os.path.exists(source_path):
            try:
                os.remove(source_path)
            except Exception:
                pass
        if os.path.exists(compressed_path):
            try:
                os.remove(compressed_path)
            except Exception:
                pass
        raise ValueError("Video invalide, illisible ou trop lourde.")
    except Exception as exc:
        if os.path.exists(source_path):
            try:
                os.remove(source_path)
            except Exception:
                pass
        raise ValueError("Video invalide ou non lisible.") from exc


def delete_product_video(relative_path: str | None) -> bool:
    normalized = (relative_path or "").replace("\\", "/").lstrip("/")
    if not normalized:
        return False

    abs_path = os.path.abspath(os.path.join(current_app.static_folder, normalized))
    static_root = os.path.abspath(current_app.static_folder)
    if not abs_path.startswith(static_root):
        return False
    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        return False
    try:
        os.remove(abs_path)
        return True
    except Exception:
        return False
