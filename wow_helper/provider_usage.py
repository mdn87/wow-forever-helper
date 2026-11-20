"""Interpret read-only provider reports. Percentages never authorize or refuse a send."""
from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import time
import threading
import weakref

from .codex_chat import ChatError

FRESH_SECONDS = 300


@dataclass(frozen=True)
class AccountUsage:
    account: str = ''
    checked: float = 0
    windows: tuple = ()
    ordinary: bool | None = None
    hard_stop: bool = False
    extras: bool = False
    failed: bool = False

    @classmethod
    def from_codex(cls, data, model='', now=None):
        buckets = data.get('rateLimitsByLimitId') or {}
        base = buckets.get('codex') or data.get('rateLimits') or {}
        selected = buckets.get(model) or {}
        relevant = [base, selected]
        windows = []
        for name, bucket in (buckets or {'Codex': base}).items():
            if not isinstance(bucket, dict):
                continue
            for field in ('primary', 'secondary'):
                item = bucket.get(field) or {}
                used = item.get('usedPercent')
                if type(used) in (int, float):
                    minutes = item.get('windowDurationMins')
                    window = {300: '5 hours', 10080: '7 days'}.get(minutes, f'{minutes} min' if minutes else field)
                    windows.append(f'{bucket.get("limitName") or name} · {window} · {used:g}% used')
        account = data.get('accountId')
        scope = hashlib.sha256(account.encode()).hexdigest() if isinstance(account, str) and account else ''
        allowed = data.get('ordinaryUsageAllowed')
        hard = any(b.get('spendControlReached') is True or
                   str(b.get('rateLimitReachedType', '')).startswith('workspace_') for b in relevant)
        credits = base.get('credits') or {}
        extra = bool(scope and not hard and base.get('spendControlReached') is False and
                     (credits.get('hasCredits') is True or credits.get('unlimited') is True))
        return cls(scope, time.time() if now is None else now, tuple(windows),
                   allowed if type(allowed) is bool else None, hard, extra)

    def unavailable(self):
        return replace(self, failed=True)

    def fresh(self):
        return bool(self.checked and not self.failed and 0 <= time.time() - self.checked <= FRESH_SECONDS)

    def paused(self):
        return self.fresh() and (self.hard_stop or self.ordinary is False)

    def describe(self):
        if not self.checked:
            return 'Usage unavailable. Check usage in Codex.'
        age = max(0, int((time.time() - self.checked) / 60))
        stamp = datetime.fromtimestamp(self.checked).strftime('%H:%M')
        status = f'Checked {stamp}' if self.fresh() else f'Stale · checked {stamp}, {age} min ago'
        if self.failed:
            status += ' · refresh failed'
        lines = [f'Codex account · {status}', *self.windows]
        if self.hard_stop:
            lines.append('The provider reports a spending limit.')
        elif self.ordinary is False:
            lines.append('Ordinary included usage is not allowed by the provider.')
        elif self.ordinary is True:
            lines.append('The provider reports ordinary included usage is available.')
        elif not self.windows:
            lines.append('Usage unavailable. Check usage in Codex.')
        return '\n'.join(lines)


@dataclass(frozen=True)
class BillingConsent:
    account: str
    request_id: str
    choice: object
    research_epoch: int | None
    text_digest: bytes

    @classmethod
    def for_request(cls, account, request_id, choice, research_epoch, body):
        return cls(account, request_id, choice, research_epoch, hashlib.sha256(body.encode()).digest())


class UsageScope:
    """Reject late readings after another companion window observes an account switch."""
    _scopes = weakref.WeakValueDictionary()
    _registry_lock = threading.Lock()

    @classmethod
    def shared(cls, storage):
        with cls._registry_lock:
            return cls._scopes.setdefault(storage.resolve(), cls())

    def __init__(self):
        self.lock = threading.Lock()
        self.sequence = self.latest = 0
        self.account = ''

    def begin(self):
        with self.lock:
            self.sequence += 1
            return self.sequence

    def accept(self, sequence, reading):
        with self.lock:
            if sequence < self.latest and self.account != reading.account:
                raise ChatError('The provider account changed. Refresh account usage.')
            if sequence >= self.latest and not reading.failed:
                self.latest, self.account = sequence, reading.account

    def current(self, reading):
        with self.lock:
            return not reading.checked or self.account == reading.account


class UsageDecision(ChatError):
    def __init__(self, usage, consent=None):
        super().__init__('The provider reports a spending limit.' if usage.hard_stop else
                         'Codex reports that ordinary included usage is unavailable.')
        self.usage, self.consent = usage, consent
