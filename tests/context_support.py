"""Shared synthetic packets for the context channel tests. Every value here is invented."""
import copy

from wow_helper.context.envelope import parse_envelope, serialize

NOW = 1790000000


def packet(**changes):
    base = {
        "v": 1,
        "kind": "context",
        "sid": "0123456789abcdef",
        "seq": 7,
        "at": NOW,
        "build": {"version": "1.60.1", "build": "70532", "interface": 16001},
        "who": {"ref": "a1b2c3d4e5f60718", "level": 12, "class": "WARRIOR"},
        "where": {"zone": "Testvale", "sub": "Example Crossing", "map": 9001},
        "quest": {
            "id": 900001,
            "pick": "tracked",
            "title": "Synthetic Delivery",
            "complete": False,
            "objectives": [{"text": "Boars slain: 3/8", "have": 3, "need": 8, "done": False}],
        },
        "scope": {"quests": "one"},
        "missing": [],
    }
    base.update(copy.deepcopy(changes))
    return base


def payload(**changes):
    """The packet as the bytes both transports carry."""
    return serialize(packet(**changes)).encode("utf-8")


def envelope(**changes):
    return parse_envelope(payload(**changes))
