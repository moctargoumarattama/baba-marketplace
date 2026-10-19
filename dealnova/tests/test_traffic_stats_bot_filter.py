import pytest
from flask import Flask
from dealnova.app.services.traffic_stats import (
    ACTIVE_TTL_SECONDS,
    is_bot_or_crawler,
    _detect_device,
    _role_bucket,
    _visitor_id,
)


def test_active_ttl_is_two_minutes():
    """Ensure active visitor window is 120 seconds for accurate live metrics."""
    assert ACTIVE_TTL_SECONDS == 120


def test_bot_detection_detects_common_crawlers_and_scripts():
    crawlers = [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Mozilla/5.0 (compatible; Google-InspectionTool/1.0;)",
        "Mediapartners-Google",
        "mediapartners-google",
        "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
        "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)",
        "Mozilla/5.0 (compatible; SemrushBot/7~bl; +http://www.semrush.com/bot.html)",
        "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
        "Mozilla/5.0 (compatible; PetalBot;+https://aspiegel.com/petalbot)",
        "python-requests/2.31.0",
        "curl/8.4.0",
        "Wget/1.21.3",
        "Go-http-client/1.1",
        "PostmanRuntime/7.36.0",
        "UptimeRobot/2.0 (http://www.uptimerobot.com/)",
        "Better Uptime Bot",
        "WhatsApp/2.23.20.76 A",
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "",  # Empty UA is assumed automated
    ]

    for ua in crawlers:
        assert is_bot_or_crawler(ua) is True, f"Failed to detect bot for UA: {ua}"


def test_bot_detection_allows_real_human_browsers():
    real_browsers = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]

    for ua in real_browsers:
        assert is_bot_or_crawler(ua) is False, f"Falsely flagged human browser as bot: {ua}"


def test_bot_request_context_device_and_role():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"

    # Human request
    with app.test_request_context(
        "/shop",
        headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile Safari/604.1"},
    ):
        assert is_bot_or_crawler() is False
        assert _detect_device() == "mobile"
        assert _role_bucket() == "guest"

    # Bot request
    with app.test_request_context(
        "/shop/product/12",
        headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"},
    ):
        assert is_bot_or_crawler() is True
        assert _detect_device() == "bot"
        assert _role_bucket() == "bot"
        assert _visitor_id() == "bot:crawler"

