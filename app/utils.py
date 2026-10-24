"""Small helpers: Persian digits, relative time, text cleaning."""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import get_settings

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_digits(value) -> str:
    return str(value).translate(_FA_DIGITS)


def fa_number(value: int | float | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        s = f"{value:,.1f}"
    else:
        s = f"{int(value):,}"
    return s.translate(_FA_DIGITS).replace(",", "٬")


def compact_number(value: int | None) -> str:
    """12345 -> ۱۲٫۳k style used on cards."""
    if value is None:
        return ""
    v = int(value)
    if v >= 1_000_000:
        s = f"{v / 1_000_000:.1f}M"
    elif v >= 10_000:
        s = f"{v / 1000:.0f}k"
    elif v >= 1_000:
        s = f"{v / 1000:.1f}k"
    else:
        s = str(v)
    return s.translate(_FA_DIGITS).replace(".", "٫")


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz())


def time_ago(dt: datetime | None, now: datetime | None = None) -> str:
    if dt is None:
        return ""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    delta: timedelta = now - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return "همین حالا"
    mins = secs // 60
    if mins < 60:
        return f"{fa_digits(mins)} دقیقه پیش"
    hours = mins // 60
    if hours < 24:
        return f"{fa_digits(hours)} ساعت پیش"
    days = hours // 24
    if days == 1:
        return "دیروز"
    if days < 30:
        return f"{fa_digits(days)} روز پیش"
    months = days // 30
    if months < 12:
        return f"{fa_digits(months)} ماه پیش"
    return f"{fa_digits(days // 365)} سال پیش"


def jalali_date(dt: datetime | None) -> str:
    """Gregorian -> Jalali (Shamsi) date string like ۱۴۰۵/۰۸/۰۲."""
    if dt is None:
        return ""
    local = to_local(dt)
    assert local is not None
    jy, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
    return fa_digits(f"{jy}/{jm:02d}/{jd:02d}")


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    jy = 979 if gy > 1600 else 0
    gy -= 1600 if gy > 1600 else 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_NL_RE = re.compile(r"\n{3,}")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = _NL_RE.sub("\n\n", text)
    return text.strip()


def truncate(text: str | None, limit: int, suffix: str = "…") -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + suffix


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def normalize_url(url: str) -> str:
    url = url.strip()
    url = re.sub(r"[?&](utm_[a-z]+|ref|source|fbclid|gclid)=[^&#]*", "", url)
    url = url.replace("?&", "?").rstrip("?&")
    if url.startswith("http://"):
        url = "https://" + url[7:]
    return url.rstrip("/")


def parse_dt(value) -> datetime | None:
    """Parse ISO-8601 / RFC-2822 timestamps into naive UTC datetimes."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            from email.utils import parsedate_to_datetime

            try:
                dt = parsedate_to_datetime(s)
            except Exception:
                return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def github_lang_slug(lang: str) -> str:
    return lang.lower().replace("#", "%23").replace("+", "%2B").replace(" ", "-")
