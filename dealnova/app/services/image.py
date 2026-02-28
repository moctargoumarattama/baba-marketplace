# dealnova/app/services/image.py
import os
import uuid
from werkzeug.utils import secure_filename
from flask import current_app
from PIL import Image, ImageOps

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
THUMB_SIZE = 300
LARGE_SIZE = 900

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def _variant_name(filename: str, size: int) -> str:
    base, _ = os.path.splitext(filename)
    return f"{base}_{size}.webp"

def _save_variant(img: Image.Image, path: str, size: int, crop_square: bool) -> None:
    if crop_square:
        variant = ImageOps.fit(img, (size, size), method=Image.LANCZOS, centering=(0.5, 0.5))
    else:
        variant = img.copy()
        variant.thumbnail((size, size), Image.LANCZOS)
    variant.save(path, "WEBP", quality=86, method=6)

def save_image(file_storage) -> str | None:
    """
    Sauvegarde une image dans: <app.static_folder>/uploads
    Retourne uniquement le filename (ex: abcd.png)
    """
    if not file_storage or not file_storage.filename:
        return None

    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit(".", 1)[-1].lower()
    new_name = f"{uuid.uuid4().hex}.{ext}"

    upload_dir = os.path.join(current_app.static_folder, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    path = os.path.join(upload_dir, new_name)
    file_storage.save(path)

    # Variantes (thumb + large) en WebP
    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            thumb_path = os.path.join(upload_dir, _variant_name(new_name, THUMB_SIZE))
            large_path = os.path.join(upload_dir, _variant_name(new_name, LARGE_SIZE))
            _save_variant(img, thumb_path, THUMB_SIZE, crop_square=True)
            _save_variant(img, large_path, LARGE_SIZE, crop_square=False)
    except Exception:
        pass

    return new_name

def image_variant(filename: str, size: str = "thumb") -> str:
    if not filename:
        return filename
    size_px = THUMB_SIZE if size in ("thumb", "small") else LARGE_SIZE
    variant = _variant_name(filename, size_px)
    upload_dir = os.path.join(current_app.static_folder, "uploads")
    if os.path.exists(os.path.join(upload_dir, variant)):
        return variant
    return filename
