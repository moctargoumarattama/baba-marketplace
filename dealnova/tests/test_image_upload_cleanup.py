"""Image processing failures never retain partial files or remove older uploads."""

from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest
from werkzeug.datastructures import FileStorage

from dealnova.tests.test_product_video_upload import video_service


def image_upload():
    source = BytesIO()
    Image.new("RGB", (80, 80), "green").save(source, format="PNG")
    source.seek(0)
    return FileStorage(source, filename="fixture.png")


@pytest.mark.parametrize("failed_variant", [300, 900])
def test_partial_image_variant_failure_removes_only_this_upload(video_service, monkeypatch, failed_variant):
    service, video_root = video_service
    upload_root = video_root.parent
    upload_root.mkdir(parents=True, exist_ok=True)
    existing = upload_root / "older-image.webp"
    existing.write_bytes(b"existing-upload")
    generated = []

    def save_variant(image, path, size, crop_square):
        Path(path).write_bytes(b"partial-variant")
        generated.append(Path(path))
        if size == failed_variant:
            raise OSError("fixture write failure")

    monkeypatch.setattr(service, "_save_variant", save_variant)
    assert service.save_image(image_upload()) is None
    assert generated
    assert list(upload_root.iterdir()) == [existing]
    assert existing.read_bytes() == b"existing-upload"


def test_failed_original_fallback_removes_partial_original_and_webp(video_service, monkeypatch):
    service, video_root = video_service

    def fail_webp(image, path, **kwargs):
        Path(path).write_bytes(b"partial-webp")
        raise OSError("fixture encoder failure")

    upload = image_upload()

    def fail_original(path):
        Path(path).write_bytes(b"partial-original")
        raise OSError("fixture storage failure")

    monkeypatch.setattr(service, "_save_webp", fail_webp)
    monkeypatch.setattr(upload, "save", fail_original)
    assert service.save_image(upload) is None
    assert list(video_root.parent.iterdir()) == []


@pytest.mark.parametrize("fallback", [False, True])
def test_successful_image_storage_keeps_result(video_service, monkeypatch, fallback):
    service, video_root = video_service
    if fallback:
        monkeypatch.setattr(service, "_save_webp", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("fixture encoder unavailable")))
    filename = service.save_image(image_upload())
    assert filename
    assert (video_root.parent / filename).is_file()
    assert len(list(video_root.parent.iterdir())) == (1 if fallback else 3)
