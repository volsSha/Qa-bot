from __future__ import annotations

from urllib.parse import urlparse

from qa_bot.config import _SCREENSHOTS_DIR
from qa_bot.services.reporter import _url_to_filename

_STATUS_BADGE: dict[str | None, tuple[str, str]] = {
    "healthy": (
        "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
        "Healthy",
    ),
    "degraded": (
        "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
        "Degraded",
    ),
    "broken": (
        "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
        "Broken",
    ),
    None: (
        "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-300",
        "Not scanned",
    ),
}


def parse_urls(text: str) -> list[str]:
    urls = [line.strip() for line in text.strip().splitlines() if line.strip()]
    valid = []
    for u in urls:
        parsed = urlparse(u)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            valid.append(u)
    return valid


def validate_single_url(text: str) -> str | None:
    parsed = urlparse(text.strip())
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return text.strip()
    return None


def status_badge(status: str | None) -> str:
    color_classes, label = _STATUS_BADGE.get(status, _STATUS_BADGE[None])
    return (
        f'<span class="{color_classes} px-2 py-0.5 rounded-full text-xs">'
        f"{label}</span>"
    )


def score_badge(score: float | None) -> str:
    if score is None:
        return ""
    if score >= 80:
        color = "text-green-600 dark:text-green-400"
    elif score >= 50:
        color = "text-yellow-600 dark:text-yellow-400"
    else:
        color = "text-red-600 dark:text-red-400"
    return f'<span class="{color} font-bold">{score:.0f}</span>'


def severity_badge(severity: str | None) -> str:
    mapping = {
        "pass": "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
        "critical": "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
        "warning": (
            "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200"
        ),
        "info": "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    }
    cls = mapping.get(severity, "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200")
    label = severity.capitalize() if severity else "?"
    return f'<span class="{cls} px-2 py-0.5 rounded text-xs">{label}</span>'


def plural(n: int) -> str:
    return "s" if n != 1 else ""


def find_latest_screenshot(url: str) -> str | None:
    prefix = _url_to_filename(url)
    files = sorted(_SCREENSHOTS_DIR.glob(f"{prefix}_*.png"), reverse=True)
    if files:
        return files[0].name
    return None


def regression_badge(has_regression: bool) -> str:
    if has_regression:
        return (
            '<span class="bg-orange-100 text-orange-800 dark:bg-orange-900 '
            'dark:text-orange-200 px-2 py-0.5 rounded-full text-xs">'
            'Visual change</span>'
        )
    return ""
