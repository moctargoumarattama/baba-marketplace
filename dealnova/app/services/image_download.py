"""Create a branded download without changing the photo displayed or stored."""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


WATERMARK_TEXT = "BABA MARKET"
MAX_DOWNLOAD_EDGE = 2560
MAX_SOURCE_PIXELS = 40_000_000


def watermarked_photo(upload_root: str | Path, filename: str) -> BytesIO:
    root = Path(upload_root).resolve()
    if not filename or "/" in filename or "\\" in filename or Path(filename).name != filename:
        raise FileNotFoundError("Photo unavailable")
    source = root / filename
    if source.is_symlink() or not source.resolve().is_relative_to(root) or not source.is_file():
        raise FileNotFoundError("Photo unavailable")
    with Image.open(source) as original:
        if original.width * original.height > MAX_SOURCE_PIXELS:
            raise ValueError("Photo too large")
        image = ImageOps.exif_transpose(original)
        image.thumbnail((MAX_DOWNLOAD_EDGE, MAX_DOWNLOAD_EDGE), Image.Resampling.LANCZOS)
        image = image.convert("RGBA")

    # Size the lettering to the image, with an outline visible on light photos.
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 80)
    except OSError:
        try:
            font = ImageFont.truetype("arialbd.ttf", 80)
        except OSError:
            try:
                font = ImageFont.load_default(size=80)
            except TypeError:  # Older Pillow versions expose the bitmap font only.
                font = ImageFont.load_default()
    bounds = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox(
        (0, 0), WATERMARK_TEXT, font=font, stroke_width=2,
    )
    label = Image.new("RGBA", (bounds[2] - bounds[0] + 12, bounds[3] - bounds[1] + 12))
    ImageDraw.Draw(label).text(
        (6 - bounds[0], 6 - bounds[1]), WATERMARK_TEXT, font=font,
        fill=(255, 255, 255, 135), stroke_width=2, stroke_fill=(0, 0, 0, 85),
    )
    width = max(1, int(image.width * .72))
    height = max(1, round(label.height * width / label.width))
    label = label.resize((width, height), Image.Resampling.LANCZOS)
    label = label.rotate(18, expand=True, resample=Image.Resampling.BICUBIC)
    # Portrait and landscape photos keep the full mark within their bounds.
    label.thumbnail((max(1, int(image.width * .9)), max(1, int(image.height * .65))), Image.Resampling.LANCZOS)
    image.alpha_composite(label, ((image.width - label.width) // 2, (image.height - label.height) // 2))
    background = Image.new("RGB", image.size, "white")
    background.paste(image, mask=image.getchannel("A"))
    output = BytesIO()
    background.save(output, format="JPEG", quality=92, optimize=True)
    output.seek(0)
    return output
