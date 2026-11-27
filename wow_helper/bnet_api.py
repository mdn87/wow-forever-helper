"""Stdlib Battle.net Game Data API client and strict 30-day TTL runtime cache.

Read-only client using OAuth client_credentials from environment variables
(WFH_BNET_CLIENT_ID and WFH_BNET_CLIENT_SECRET). Never stores, logs, or prints
credentials or bearer tokens, never opens a network listener, and restricts
requests to /data/wow/ game-data endpoints.
"""

from __future__ import annotations

import base64
from collections import deque
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_DIR = ROOT / ".runtime" / "bnet-cache"

ENV_CLIENT_ID = "WFH_BNET_CLIENT_ID"
ENV_CLIENT_SECRET = "WFH_BNET_CLIENT_SECRET"

TOKEN_URL = "https://oauth.battle.net/token"
ALLOWED_REGIONS = ("us", "eu", "kr", "tw")
DEFAULT_REGION = "us"
DEFAULT_LOCALE = "en_US"
DEFAULT_TIMEOUT = 25.0
DEFAULT_MIN_INTERVAL = 0.2
HOURLY_REQUEST_LIMIT = 36_000
MAX_CONSECUTIVE_5XX = 2
MAX_RESPONSE_BYTES = 64 * 1024 * 1024  # 64 MiB bounded read
TOKEN_EXPIRY_MARGIN = 60.0
CACHE_SCHEMA_VERSION = 1
MAX_TTL_SECONDS = 30 * 24 * 60 * 60  # Blizzard API Terms 30-day ceiling
MAX_NOT_FOUND_TTL_SECONDS = 24 * 60 * 60
USER_AGENT = "wow-forever-helper/0.1 (read-only game-data client)"

ATTRIBUTION = (
    "Data provided by Blizzard Entertainment via the Battle.net API "
    "(not endorsed by or affiliated with Blizzard)."
)

_LOCALE_RE = re.compile(r"^[a-z]{2}_[A-Z]{2}$")
_NAMESPACE_RE = re.compile(r"^(?:static|dynamic)(?:-[0-9A-Za-z._]+)?-forever-(?:us|eu|kr|tw)$")
_PATH_RE = re.compile(r"^/data/wow/[A-Za-z0-9/_-]+$")


class BnetApiError(Exception):
    """Base error for Battle.net API client failures."""


class BnetConfigError(BnetApiError):
    """Missing credentials or invalid region, namespace, locale, or path."""


class BnetAuthError(BnetApiError):
    """OAuth client-credentials token request failed."""


class BnetNotFoundError(BnetApiError):
    """API endpoint returned HTTP 404 Not Found."""

    def __init__(self, message: str, *, from_cache: bool = False):
        super().__init__(message)
        self.from_cache = from_cache


class BnetRateLimitError(BnetApiError):
    """API returned HTTP 429 or local hourly request budget was reached."""


class BnetServerError(BnetApiError):
    """API returned HTTP 5xx or tripped the consecutive-5xx circuit breaker."""


class BnetNetworkError(BnetApiError):
    """Transport error, timeout, oversized payload, or malformed JSON."""


@dataclass(frozen=True)
class BnetResponse:
    """Validated Game Data response with freshness metadata and attribution."""

    payload: dict | list
    namespace: str
    served_namespace: str | None
    path: str
    fetched_at: float
    expires_at: float
    from_cache: bool
    attribution: str = ATTRIBUTION

    def age_seconds(self, now: float | None = None) -> int:
        current = time.time() if now is None else float(now)
        return max(0, int(current - self.fetched_at))


def validate_region(region: str) -> str:
    if not isinstance(region, str) or region not in ALLOWED_REGIONS:
        raise BnetConfigError(f"Unsupported Battle.net region: expected one of {', '.join(ALLOWED_REGIONS)}.")
    return region


def validate_locale(locale: str) -> str:
    if not isinstance(locale, str) or not _LOCALE_RE.fullmatch(locale):
        raise BnetConfigError("Invalid Battle.net locale format; expected form like en_US.")
    return locale


def static_namespace(region: str = DEFAULT_REGION) -> str:
    return f"static-forever-{validate_region(region)}"


def dynamic_namespace(region: str = DEFAULT_REGION) -> str:
    return f"dynamic-forever-{validate_region(region)}"


def validate_namespace(namespace: str, region: str) -> str:
    validate_region(region)
    if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace) or not namespace.endswith(f"-{region}"):
        raise BnetConfigError("Invalid Forever game-data namespace for the selected region.")
    return namespace


def validate_api_path(path: str) -> str:
    if (
        not isinstance(path, str)
        or not _PATH_RE.fullmatch(path)
        or ".." in path
        or "//" in path
    ):
        raise BnetConfigError("Only read-only /data/wow/ game-data paths are permitted.")
    return path


def normalize_params(params: dict[str, str] | list[tuple[str, str]] | None) -> tuple[tuple[str, str], ...]:
    if not params:
        return ()
    items = list(params.items()) if isinstance(params, dict) else list(params)
    normalized: list[tuple[str, str]] = []
    for key, value in items:
        if not isinstance(key, str) or not key or key in {"namespace", "locale", "access_token"}:
            raise BnetConfigError("Invalid or reserved Battle.net query parameter.")
        normalized.append((key, str(value)))
    normalized.sort()
    return tuple(normalized)


def extract_served_namespace(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    links = payload.get("_links")
    if not isinstance(links, dict):
        return None
    self_link = links.get("self")
    if not isinstance(self_link, dict):
        return None
    href = self_link.get("href")
    if not isinstance(href, str):
        return None
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
    values = query.get("namespace")
    return values[0] if values and isinstance(values[0], str) else None


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        deadline = time.monotonic() + 0.5
        while True:
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _safe_unlink(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False


class BnetCache:
    """File-backed JSON cache under ignored runtime storage with strict <=30-day TTL."""

    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE_DIR, *, clock=time.time):
        self.cache_dir = Path(cache_dir)
        self._clock = clock

    def key_for(
        self,
        *,
        region: str,
        namespace: str,
        locale: str,
        path: str,
        params: tuple[tuple[str, str], ...] = (),
    ) -> str:
        canonical = json.dumps(
            {
                "region": region,
                "namespace": namespace,
                "locale": locale,
                "path": path,
                "params": list(params),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _entry_path(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("Invalid cache key.")
        return self.cache_dir / f"{key}.json"

    def _is_valid_envelope(self, raw: object, now: float) -> bool:
        if not isinstance(raw, dict):
            return False
        if raw.get("schema_version") != CACHE_SCHEMA_VERSION:
            return False
        fetched_at = raw.get("fetched_at")
        expires_at = raw.get("expires_at")
        if not isinstance(fetched_at, (int, float)) or not isinstance(expires_at, (int, float)):
            return False
        if isinstance(fetched_at, bool) or isinstance(expires_at, bool):
            return False
        if now >= expires_at:
            return False
        # Hard Blizzard Terms ceiling: never serve data older than 30 days from fetch time.
        if (now - fetched_at) >= MAX_TTL_SECONDS:
            return False
        if fetched_at > now + 300:
            return False
        return True

    def get(
        self,
        *,
        region: str,
        namespace: str,
        locale: str,
        path: str,
        params: tuple[tuple[str, str], ...] = (),
    ) -> dict | None:
        key = self.key_for(region=region, namespace=namespace, locale=locale, path=path, params=params)
        entry_path = self._entry_path(key)
        if not entry_path.exists():
            return None
        try:
            raw = json.loads(entry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _safe_unlink(entry_path)
            return None
        now = float(self._clock())
        if not self._is_valid_envelope(raw, now):
            _safe_unlink(entry_path)
            return None
        return raw

    def put(
        self,
        *,
        region: str,
        namespace: str,
        locale: str,
        path: str,
        params: tuple[tuple[str, str], ...] = (),
        ttl_seconds: int | float,
        payload: dict | list | None,
        served_namespace: str | None = None,
        status: int = 200,
    ) -> dict:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
            raise ValueError("ttl_seconds must be a positive number.")
        if ttl_seconds <= 0 or ttl_seconds > MAX_TTL_SECONDS:
            raise ValueError(f"ttl_seconds must be > 0 and <= {MAX_TTL_SECONDS} (30 days).")
        if status == 404 and ttl_seconds > MAX_NOT_FOUND_TTL_SECONDS:
            raise ValueError(f"Negative 404 cache TTL must be <= {MAX_NOT_FOUND_TTL_SECONDS} seconds.")
        now = float(self._clock())
        envelope = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "status": int(status),
            "region": region,
            "namespace": namespace,
            "locale": locale,
            "path": path,
            "params": [list(pair) for pair in params],
            "fetched_at": now,
            "expires_at": now + float(ttl_seconds),
            "ttl_seconds": float(ttl_seconds),
            "served_namespace": served_namespace,
            "attribution": ATTRIBUTION,
            "payload": payload,
        }
        key = self.key_for(region=region, namespace=namespace, locale=locale, path=path, params=params)
        _atomic_write_json(self._entry_path(key), envelope)
        return envelope

    def purge_expired(self) -> int:
        if not self.cache_dir.exists():
            return 0
        now = float(self._clock())
        removed = 0
        for entry_path in self.cache_dir.glob("*.json"):
            try:
                raw = json.loads(entry_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                if _safe_unlink(entry_path):
                    removed += 1
                continue
            if not self._is_valid_envelope(raw, now):
                if _safe_unlink(entry_path):
                    removed += 1
        return removed

    def clear(self) -> int:
        if not self.cache_dir.exists():
            return 0
        removed = 0
        for entry_path in self.cache_dir.glob("*.json"):
            if _safe_unlink(entry_path):
                removed += 1
        return removed


def _default_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
    max_bytes: int,
) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise BnetNetworkError(f"Battle.net response exceeded {max_bytes} byte limit.")
            return int(resp.status), raw
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read(min(max_bytes, 65_536))
        except Exception:
            raw = b""
        return int(exc.code), raw
    except BnetApiError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BnetNetworkError(f"Battle.net request failed: {type(exc).__name__}.") from None


class BnetClient:
    """Rate-limited Battle.net Game Data client backed by a 30-day max TTL cache."""

    def __init__(
        self,
        *,
        region: str = DEFAULT_REGION,
        locale: str = DEFAULT_LOCALE,
        cache: BnetCache | None = None,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        env: dict[str, str] | None = None,
        transport=None,
        clock=time.time,
        monotonic=time.monotonic,
        sleep=time.sleep,
        timeout: float = DEFAULT_TIMEOUT,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        max_requests_per_hour: int = HOURLY_REQUEST_LIMIT,
        max_consecutive_5xx: int = MAX_CONSECUTIVE_5XX,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ):
        self.region = validate_region(region)
        self.locale = validate_locale(locale)
        self.cache = cache if cache is not None else BnetCache(cache_dir, clock=clock)
        self._env = os.environ if env is None else env
        self._transport = _default_transport if transport is None else transport
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep
        self.timeout = float(timeout)
        self.min_interval = max(0.0, float(min_interval))
        self.max_requests_per_hour = max(1, int(max_requests_per_hour))
        self.max_consecutive_5xx = max(1, int(max_consecutive_5xx))
        self.max_response_bytes = max(1024, int(max_response_bytes))

        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._last_request_mono: float | None = None
        self._hourly_timestamps: deque[float] = deque()
        self._consecutive_5xx = 0

    def __repr__(self) -> str:
        return f"BnetClient(region={self.region!r}, locale={self.locale!r})"

    def reset_circuit_breaker(self) -> None:
        self._consecutive_5xx = 0

    def _read_credentials(self) -> tuple[str, str]:
        client_id = str(self._env.get(ENV_CLIENT_ID) or "").strip()
        client_secret = str(self._env.get(ENV_CLIENT_SECRET) or "").strip()
        if not client_id or not client_secret:
            raise BnetConfigError(
                f"Battle.net credentials missing: set {ENV_CLIENT_ID} and {ENV_CLIENT_SECRET} in the environment."
            )
        return client_id, client_secret

    def _acquire_token(self) -> str:
        now = float(self._clock())
        if self._access_token and now < (self._token_expires_at - TOKEN_EXPIRY_MARGIN):
            return self._access_token

        client_id, client_secret = self._read_credentials()
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("ascii")
        headers = {
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        status, raw = self._transport("POST", TOKEN_URL, headers, body, self.timeout, 65_536)
        if status == 401:
            raise BnetAuthError(
                f"Battle.net token request returned HTTP 401 "
                f"(client ID length {len(client_id)}, client secret length {len(client_secret)})."
            )
        if status == 429:
            raise BnetRateLimitError("Battle.net token endpoint returned HTTP 429.")
        if status >= 500:
            raise BnetServerError(f"Battle.net token endpoint returned HTTP {status}.")
        if status != 200:
            raise BnetAuthError(f"Battle.net token request failed with HTTP {status}.")

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise BnetNetworkError("Battle.net token endpoint returned invalid JSON.") from None

        token = data.get("access_token") if isinstance(data, dict) else None
        expires_in = data.get("expires_in") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise BnetAuthError("Battle.net token response did not include an access token.")
        lifetime = float(expires_in) if isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool) and expires_in > 0 else 3600.0

        self._access_token = token
        self._token_expires_at = float(self._clock()) + lifetime
        return token

    def _enforce_rate_limits(self) -> None:
        if self._consecutive_5xx >= self.max_consecutive_5xx:
            raise BnetServerError(
                f"Battle.net client stopped after {self._consecutive_5xx} consecutive HTTP 5xx responses."
            )
        now_mono = float(self._monotonic())
        if self._last_request_mono is not None and self.min_interval > 0:
            wait = self.min_interval - (now_mono - self._last_request_mono)
            if wait > 0:
                self._sleep(wait)
                now_mono = float(self._monotonic())

        cutoff = now_mono - 3600.0
        while self._hourly_timestamps and self._hourly_timestamps[0] <= cutoff:
            self._hourly_timestamps.popleft()
        if len(self._hourly_timestamps) >= self.max_requests_per_hour:
            raise BnetRateLimitError(
                f"Local hourly Battle.net request limit ({self.max_requests_per_hour}/hour) reached."
            )
        self._hourly_timestamps.append(now_mono)
        self._last_request_mono = now_mono

    def get_json(
        self,
        path: str,
        *,
        namespace: str | None = None,
        params: dict[str, str] | list[tuple[str, str]] | None = None,
        ttl_seconds: int | float = 3600,
        not_found_ttl: int | float | None = None,
        cache_only: bool = False,
        force_refresh: bool = False,
    ) -> BnetResponse | None:
        clean_path = validate_api_path(path)
        ns = static_namespace(self.region) if namespace is None else validate_namespace(namespace, self.region)
        clean_params = normalize_params(params)

        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
            raise ValueError("ttl_seconds must be a positive number.")
        if ttl_seconds <= 0 or ttl_seconds > MAX_TTL_SECONDS:
            raise ValueError(f"ttl_seconds must be > 0 and <= {MAX_TTL_SECONDS} (30 days).")
        if not_found_ttl is not None:
            if isinstance(not_found_ttl, bool) or not isinstance(not_found_ttl, (int, float)):
                raise ValueError("not_found_ttl must be a positive number.")
            if not_found_ttl <= 0 or not_found_ttl > MAX_NOT_FOUND_TTL_SECONDS:
                raise ValueError(f"not_found_ttl must be > 0 and <= {MAX_NOT_FOUND_TTL_SECONDS}.")

        if not force_refresh:
            cached = self.cache.get(
                region=self.region,
                namespace=ns,
                locale=self.locale,
                path=clean_path,
                params=clean_params,
            )
            if cached is not None:
                if cached.get("status") == 404:
                    raise BnetNotFoundError(
                        f"Battle.net endpoint {clean_path} returned HTTP 404 (cached).",
                        from_cache=True,
                    )
                payload = cached.get("payload")
                if isinstance(payload, (dict, list)):
                    return BnetResponse(
                        payload=payload,
                        namespace=ns,
                        served_namespace=cached.get("served_namespace"),
                        path=clean_path,
                        fetched_at=float(cached["fetched_at"]),
                        expires_at=float(cached["expires_at"]),
                        from_cache=True,
                        attribution=ATTRIBUTION,
                    )

        if cache_only:
            return None

        token = self._acquire_token()
        self._enforce_rate_limits()

        query_items = [("namespace", ns), ("locale", self.locale), *clean_params]
        url = f"https://{self.region}.api.blizzard.com{clean_path}?{urllib.parse.urlencode(query_items)}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        status, raw = self._transport("GET", url, headers, None, self.timeout, self.max_response_bytes)

        if status == 401:
            self._access_token = None
            self._token_expires_at = 0.0
            raise BnetAuthError("Battle.net API rejected the bearer token with HTTP 401.")
        if status == 429:
            self._consecutive_5xx = 0
            raise BnetRateLimitError(f"Battle.net API rate-limited {clean_path} with HTTP 429.")
        if status >= 500:
            self._consecutive_5xx += 1
            raise BnetServerError(f"Battle.net API returned HTTP {status} for {clean_path}.")

        self._consecutive_5xx = 0

        if status == 404:
            if not_found_ttl is not None:
                self.cache.put(
                    region=self.region,
                    namespace=ns,
                    locale=self.locale,
                    path=clean_path,
                    params=clean_params,
                    ttl_seconds=not_found_ttl,
                    payload=None,
                    served_namespace=None,
                    status=404,
                )
            raise BnetNotFoundError(f"Battle.net API returned HTTP 404 for {clean_path}.", from_cache=False)

        if status != 200:
            raise BnetApiError(f"Battle.net API returned unexpected HTTP {status} for {clean_path}.")

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise BnetNetworkError(f"Battle.net API returned invalid JSON for {clean_path}.") from None

        if not isinstance(payload, (dict, list)):
            raise BnetNetworkError(f"Battle.net API returned unexpected JSON root for {clean_path}.")

        served_ns = extract_served_namespace(payload)
        envelope = self.cache.put(
            region=self.region,
            namespace=ns,
            locale=self.locale,
            path=clean_path,
            params=clean_params,
            ttl_seconds=ttl_seconds,
            payload=payload,
            served_namespace=served_ns,
            status=200,
        )
        return BnetResponse(
            payload=payload,
            namespace=ns,
            served_namespace=served_ns,
            path=clean_path,
            fetched_at=float(envelope["fetched_at"]),
            expires_at=float(envelope["expires_at"]),
            from_cache=False,
            attribution=ATTRIBUTION,
        )
