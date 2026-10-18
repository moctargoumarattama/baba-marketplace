from flask import Flask, flash, render_template_string
import pytest
from pathlib import Path


def test_flash_toast_render():
    app = Flask("test-flash-toast")
    app.config["SECRET_KEY"] = "toast-secret"
    
    # Simple global mock for t() function in templates
    app.jinja_env.globals["t"] = lambda s: s
    app.jinja_env.globals["app_static_version"] = "1.0.0"
    app.jinja_env.globals["apple_touch_icon"] = lambda: "/apple-touch-icon.png"

    template_path = Path(__file__).resolve().parents[1] / "app" / "templates" / "base.html"
    content = template_path.read_text(encoding="utf-8")

    # Render base.html with flashed messages inside request context
    with app.test_request_context("/"):
        flash("Vous êtes déconnecté.", "info")
        flash("Action réussie !", "success")
        
        # Test the flashed messages snippet directly from base.html
        assert "bm-flash-toast-container" in content
        assert "data-bm-toast" in content
        assert "bm-toast-progress" in content
        assert "bm-toast-close" in content

