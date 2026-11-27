"""Hands-free voice Battle.net Forever item and Auction House lookup adapter.

Runs read-only cached item-stat and AH price lookups for Lugos Voice turns,
attaching Blizzard attribution and signaling voice-browser fallback when an
item is missing from the Forever item API (HTTP 404 / 0 hits) or credentials
are not configured.
"""

from __future__ import annotations

from dataclasses import dataclass
import os

from .bnet_api import (
    ATTRIBUTION,
    BnetApiError,
    BnetClient,
    BnetConfigError,
    BnetNotFoundError,
)
from . import bnet_items, bnet_market

ENV_RULESET_ID = "WFH_BNET_RULESET_ID"
ENV_HOUSE_ID = "WFH_BNET_HOUSE_ID"
DEFAULT_RULESET_ID = 1
DEFAULT_HOUSE_ID = 110
MAX_SPOKEN_CHARS = 900


@dataclass(frozen=True)
class BnetVoiceResult:
    status: str  # "done" | "rejected" | "failed" | "fallback"
    detail: str
    fallback_query: str | None = None


def _env_int(env, key: str, default: int) -> int:
    raw = str(env.get(key) or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return default


class BnetVoiceLookup:
    """Bounded read-only Battle.net lookup worker for hands-free voice turns."""

    def __init__(
        self,
        *,
        client_factory=BnetClient,
        ruleset_id: int | None = None,
        house_id: int | None = None,
        env=None,
    ):
        self._client_factory = client_factory
        self._client: BnetClient | None = None
        source_env = os.environ if env is None else env
        self.ruleset_id = ruleset_id if ruleset_id is not None else _env_int(source_env, ENV_RULESET_ID, DEFAULT_RULESET_ID)
        self.house_id = house_id if house_id is not None else _env_int(source_env, ENV_HOUSE_ID, DEFAULT_HOUSE_ID)

    @property
    def client(self) -> BnetClient:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def run(self, action: str, argument: str) -> BnetVoiceResult:
        query = str(argument or "").strip()
        if not query:
            return BnetVoiceResult("rejected", "Name an item to look up.")
        if action == "item":
            return self._lookup_item(query)
        if action == "market":
            return self._lookup_market(query)
        return BnetVoiceResult("rejected", f"Unsupported Battle.net voice lookup action: {action}.")

    def _lookup_item(self, query: str) -> BnetVoiceResult:
        try:
            if query.isdigit():
                outcome = bnet_items.lookup_item(self.client, int(query))
            else:
                search = bnet_items.search_items(self.client, query, page_size=5)
                results = search.get("results") or []
                if not results:
                    return BnetVoiceResult(
                        "fallback",
                        f"{query} was not found in the Forever item API.",
                        fallback_query=query,
                    )
                exact = next((r for r in results if str(r.get("name") or "").casefold() == query.casefold()), None)
                chosen = exact or results[0]
                outcome = bnet_items.lookup_item(self.client, int(chosen["id"]))
        except (BnetNotFoundError, BnetConfigError):
            return BnetVoiceResult(
                "fallback",
                f"{query} is unavailable from the Forever item API.",
                fallback_query=query,
            )
        except BnetApiError as error:
            return BnetVoiceResult("rejected", str(error)[:MAX_SPOKEN_CHARS])

        if outcome.get("status") != "ok":
            return BnetVoiceResult(
                "fallback",
                f"{query} was not found in the Forever item API.",
                fallback_query=query,
            )
        summary = bnet_items.format_item_summary(outcome["item"])
        detail = f"{summary}. {ATTRIBUTION}"[:MAX_SPOKEN_CHARS]
        return BnetVoiceResult("done", detail)

    def _lookup_market(self, query: str) -> BnetVoiceResult:
        try:
            if query.isdigit():
                result = bnet_market.price_summary(
                    self.client,
                    ruleset_id=self.ruleset_id,
                    house_id=self.house_id,
                    item_id=int(query),
                )
            else:
                result = bnet_market.price_summary(
                    self.client,
                    ruleset_id=self.ruleset_id,
                    house_id=self.house_id,
                    query=query,
                )
        except BnetApiError as error:
            return BnetVoiceResult("rejected", str(error)[:MAX_SPOKEN_CHARS])

        text = bnet_market.as_text(result).replace("\n", " ")
        return BnetVoiceResult("done", text[:MAX_SPOKEN_CHARS])
