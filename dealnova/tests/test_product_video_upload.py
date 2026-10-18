"""Video upload checks use temporary files and do not import the application."""

from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from flask import Flask
import pytest
from werkzeug.datastructures import FileStorage


@pytest.fixture
def video_service(tmp_path):
    # Loading this standalone service avoids config/.env and database imports.
    path = Path(__file__).resolve().parents[1] / "app" / "services" / "image.py"
    spec = spec_from_file_location("isolated_product_video_service", path)
    service = module_from_spec(spec)
    spec.loader.exec_module(service)
    app = Flask("product-video-upload-test", static_folder=str(tmp_path / "static"))
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    with app.app_context():
        yield service, tmp_path / "uploads" / "product_videos"


@pytest.mark.parametrize("extension", ["mp4", "mov", "webm"])
def test_video_upload_preserves_final_mp4_and_removes_distinct_source(video_service, monkeypatch, extension):
    service, video_root = video_service
    monkeypatch.setattr(service.shutil, "which", lambda executable: "ffmpeg-test")
    observed = {}

    def encode(command, **kwargs):
        source = Path(command[command.index("-i") + 1])
        destination = Path(command[-1])
        assert source.resolve() != destination.resolve()
        assert source.read_bytes() == b"source-video"
        observed["source"] = source
        destination.write_bytes(b"encoded-video")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service.subprocess, "run", encode)
    upload = FileStorage(BytesIO(b"source-video"), filename=f"video.{extension}")
    relative_path = service.save_product_video(upload)

    assert relative_path.startswith("uploads/product_videos/")
    assert relative_path.endswith(".mp4")
    final_path = video_root / Path(relative_path).name
    assert final_path.read_bytes() == b"encoded-video"
    assert not observed["source"].exists()
    assert list(video_root.iterdir()) == [final_path]


@pytest.mark.parametrize("failure", ["exit-code", "exception", "unavailable"])
def test_failed_video_upload_removes_source_and_partial_output(video_service, monkeypatch, failure):
    service, video_root = video_service
    monkeypatch.setattr(service.shutil, "which", lambda executable: None if failure == "unavailable" else "ffmpeg-test")

    def fail_encoding(command, **kwargs):
        Path(command[-1]).write_bytes(b"partial-output")
        if failure == "exception":
            raise OSError("encoder interrupted")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(service.subprocess, "run", fail_encoding)
    upload = FileStorage(BytesIO(b"source-video"), filename="video.mp4")

    with pytest.raises(ValueError):
        service.save_product_video(upload)

    assert list(video_root.iterdir()) == []
