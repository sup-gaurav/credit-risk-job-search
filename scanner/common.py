"""Shared helpers: polite HTTP client, time parsing, text normalisation."""
from __future__ import annotations

import hashlib
import html
import json
import random
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
import os as _os

DATA = Path(_os.environ.get("CRJS_DATA_DIR") or ROOT / "site" / "data")
STATE = Path(_os.environ.get("CRJS_STATE_DIR") or ROOT / "state")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj, indent=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":")),
        encoding="utf-8",
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class Throttled(Exception):
    """The source is rate limiting or blocking this runner."""


class Budget:
    """Wall-clock budget for one phase."""

    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + seconds

    @property
    def left(self) -> float:
        return self.deadline - time.monotonic()

    @property
    def spent(self) -> bool:
        return self.left <= 0


class Http:
    """Small polite client: per-host pacing, bounded retries, no bypass tricks."""

    def __init__(self, min_gap=1.2, max_gap=2.6, timeout=25):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        self.min_gap, self.max_gap, self.timeout = min_gap, max_gap, timeout
        self._locks: dict[str, threading.Lock] = {}
        self._next: dict[str, float] = {}
        self._guard = threading.Lock()
        self.requests = 0
        self.failures = 0

    def _pace(self, host: str):
        with self._guard:
            lock = self._locks.setdefault(host, threading.Lock())
        with lock:
            wait = self._next.get(host, 0) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._next[host] = time.monotonic() + random.uniform(self.min_gap, self.max_gap)

    def request(self, method, url, *, retries=2, throttle_codes=(429, 999), **kwargs):
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
        last = None
        for attempt in range(retries + 1):
            self._pace(host)
            self.requests += 1
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                last = exc
                self.failures += 1
                time.sleep(2 + attempt * 3)
                continue
            if resp.status_code in throttle_codes:
                self.failures += 1
                raise Throttled(f"HTTP {resp.status_code}")
            if resp.status_code >= 500 and attempt < retries:
                self.failures += 1
                time.sleep(3 + attempt * 4)
                continue
            return resp
        raise ConnectionError(str(last)[:200] if last else "request failed")

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


# ---------------------------------------------------------------- text

_SUFFIX = re.compile(
    r"\b(private|pvt|limited|ltd|llp|llc|inc|incorporated|corp|corporation|plc|co|company|group|"
    r"india|services|service|technologies|technology|solutions|global)\b"
)


def norm(text: str) -> str:
    text = html.unescape(text or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9+ ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def norm_company(name: str) -> str:
    base = norm(name)
    stripped = re.sub(r"\s+", " ", _SUFFIX.sub(" ", base)).strip()
    return stripped or base


def norm_title(title: str) -> str:
    text = norm(title)
    text = re.sub(r"\b(sr|snr)\b", "senior", text)
    text = re.sub(r"\bmodelling\b", "modeling", text)
    text = re.sub(r"\bvice president\b", "vp", text)
    text = re.sub(r"\bassistant vp\b|\bassociate vp\b", "avp", text)
    return text


def clean_text(value: str) -> str:
    text = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", value or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:14]


# ---------------------------------------------------------------- time

_REL = re.compile(r"(\d+)\+?\s*(second|minute|hour|day|week|month|year)s?\s+ago", re.I)
_UNIT_HOURS = {"second": 1 / 3600, "minute": 1 / 60, "hour": 1, "day": 24, "week": 168, "month": 720, "year": 8760}


def relative_bounds(text: str):
    """Return (min_hours, max_hours, precision) for strings like '3 hours ago'.

    precision is 'hour' when the source states minutes or hours, else 'day' or coarser.
    """
    if not text:
        return None
    low = text.strip().lower()
    if "just now" in low or "moments ago" in low:
        return (0.0, 1.0, "hour")
    if "today" in low:
        return (0.0, 24.0, "day")
    if "yesterday" in low:
        return (24.0, 48.0, "day")
    match = _REL.search(low)
    if not match:
        return None
    count, unit = int(match.group(1)), match.group(2)
    size = _UNIT_HOURS[unit]
    if unit in ("second", "minute"):
        return (0.0, 1.0, "hour")
    if unit == "hour":
        return (float(count), float(count + 1), "hour")
    if "+" in low:
        return (count * size, count * size * 3, "coarse")
    return (count * size, (count + 1) * size, "day" if unit == "day" else "coarse")


def posted_estimate(seen_at: datetime, bounds, window_hours: float | None = None):
    """Turn relative bounds into (posted_at, earliest, latest, precision).

    A result returned by a source-side 'last N hours' filter cannot be older than N hours,
    so the upper age bound is tightened to the filter window when one applied.
    """
    if not bounds:
        return None
    low, high, precision = bounds
    if window_hours and high > window_hours >= low:
        high = float(window_hours)
    mid = (low + high) / 2
    return (
        seen_at - timedelta(hours=mid),
        seen_at - timedelta(hours=high),
        seen_at - timedelta(hours=low),
        precision,
    )


def age_hours(posted_at: datetime | None, ref: datetime | None = None) -> float | None:
    if not posted_at:
        return None
    return max(0.0, ((ref or now_utc()) - posted_at).total_seconds() / 3600)
