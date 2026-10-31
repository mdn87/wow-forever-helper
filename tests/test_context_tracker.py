"""Freshness of context packets: duplicates, older packets, stale and future timestamps."""
import json

import pytest

from wow_helper.context.envelope import Build, Envelope
from wow_helper.context.tracker import Judgement, Tracker, VERDICTS

NOW = 1790000000.0


def packet(sid="0123456789abcdef", seq=1, at=1790000000):
    return Envelope(sid, seq, at, Build("1.60.1", "70532", 16001), None, None, None, ())


def test_the_first_packet_of_a_session_is_fresh_and_new():
    judged = Tracker().judge(packet(), NOW)
    assert judged == Judgement("fresh", 0, True, None)
    assert judged.fresh


def test_the_same_sequence_again_is_a_duplicate_and_changes_nothing():
    tracker = Tracker()
    tracker.judge(packet(seq=4), NOW)
    before = tracker.state()
    judged = tracker.judge(packet(seq=4), NOW + 1)
    assert (judged.verdict, judged.fresh, judged.new_session) == ("duplicate", False, False)
    assert tracker.state() == before


def test_a_higher_sequence_is_fresh_and_reports_how_many_were_skipped():
    tracker = Tracker()
    tracker.judge(packet(seq=4), NOW)
    consecutive = tracker.judge(packet(seq=5), NOW)
    gap = tracker.judge(packet(seq=9), NOW)
    assert (consecutive.verdict, consecutive.skipped, consecutive.new_session) == ("fresh", 0, False)
    assert (gap.verdict, gap.skipped) == ("fresh", 3)


def test_a_lower_sequence_in_the_same_session_is_older():
    tracker = Tracker()
    tracker.judge(packet(seq=8), NOW)
    assert tracker.judge(packet(seq=3), NOW).verdict == "older"
    assert tracker.judge(packet(seq=9), NOW).verdict == "fresh"


def test_a_new_session_starts_over_even_with_a_lower_sequence():
    tracker = Tracker()
    tracker.judge(packet(sid="aaaaaaaaaaaaaaaa", seq=50), NOW)
    judged = tracker.judge(packet(sid="bbbbbbbbbbbbbbbb", seq=1), NOW)
    assert (judged.verdict, judged.new_session, judged.skipped) == ("fresh", True, None)


def test_replaying_an_earlier_sessions_last_packet_is_still_caught():
    tracker = Tracker()
    tracker.judge(packet(sid="aaaaaaaaaaaaaaaa", seq=6), NOW)
    tracker.judge(packet(sid="bbbbbbbbbbbbbbbb", seq=2), NOW)
    assert tracker.judge(packet(sid="aaaaaaaaaaaaaaaa", seq=6), NOW).verdict == "duplicate"
    assert tracker.judge(packet(sid="aaaaaaaaaaaaaaaa", seq=5), NOW).verdict == "older"


def test_only_the_most_recent_sessions_are_remembered():
    tracker = Tracker(remember=3)
    for index in range(4):
        tracker.judge(packet(sid=f"{index:016x}", seq=10), NOW)
    assert len(tracker.state()["sessions"]) == 3
    forgotten = tracker.judge(packet(sid=f"{0:016x}", seq=10), NOW)
    assert (forgotten.verdict, forgotten.new_session) == ("fresh", True)


def test_a_packet_older_than_the_limit_is_stale_and_does_not_change_state():
    tracker = Tracker(max_age=120)
    stale = tracker.judge(packet(seq=9, at=1790000000 - 121), NOW)
    assert (stale.verdict, stale.age, stale.fresh) == ("stale", 121, False)
    assert tracker.state()["sessions"] == []
    assert tracker.judge(packet(seq=9), NOW).verdict == "fresh"


def test_the_age_limit_is_inclusive():
    tracker = Tracker(max_age=120)
    assert tracker.judge(packet(seq=1, at=1790000000 - 120), NOW).verdict == "fresh"
    assert Tracker(max_age=120).judge(packet(seq=1, at=1790000000 - 121), NOW).verdict == "stale"


def test_a_packet_from_the_future_beyond_the_slack_is_refused():
    tracker = Tracker(future_slack=60)
    assert tracker.judge(packet(seq=1, at=1790000000 + 61), NOW).verdict == "future"
    assert tracker.judge(packet(seq=1, at=1790000000 + 60), NOW).verdict == "fresh"
    assert tracker.judge(packet(seq=2, at=1790000000 + 5), NOW).age == -5


def test_the_clock_is_compared_in_whole_seconds():
    judged = Tracker().judge(packet(at=1790000000), NOW + 0.9)
    assert judged.age == 0


def test_a_stale_duplicate_is_reported_as_stale_not_as_a_duplicate():
    tracker = Tracker(max_age=30)
    tracker.judge(packet(seq=3), NOW)
    assert tracker.judge(packet(seq=3), NOW + 31).verdict == "stale"


def test_every_verdict_is_listed():
    assert set(VERDICTS) == {"fresh", "duplicate", "older", "stale", "future"}
    tracker = Tracker()
    seen = {tracker.judge(packet(seq=2), NOW).verdict, tracker.judge(packet(seq=2), NOW).verdict,
            tracker.judge(packet(seq=1), NOW).verdict, tracker.judge(packet(seq=3, at=1), NOW).verdict,
            tracker.judge(packet(seq=3, at=2 ** 31), NOW).verdict}
    assert seen == set(VERDICTS)


def test_state_round_trips_through_json_and_keeps_the_verdicts():
    tracker = Tracker()
    tracker.judge(packet(sid="aaaaaaaaaaaaaaaa", seq=6), NOW)
    tracker.judge(packet(sid="bbbbbbbbbbbbbbbb", seq=2), NOW)
    restored = Tracker.from_state(json.loads(json.dumps(tracker.state())))
    assert restored.judge(packet(sid="bbbbbbbbbbbbbbbb", seq=2), NOW).verdict == "duplicate"
    assert restored.judge(packet(sid="aaaaaaaaaaaaaaaa", seq=7), NOW).verdict == "fresh"


@pytest.mark.parametrize("state", [
    None, [], "text", 5, {}, {"sessions": "x"}, {"sessions": [["short", 1]]}, {"sessions": [["0123456789abcdef", True]]},
    {"sessions": [["0123456789abcdef", 0]]}, {"sessions": [["0123456789abcdef", 2 ** 40]]}, {"sessions": [[1, 2]]},
    {"sessions": [["0123456789abcdef"]]}, {"sessions": [None]}, {"sessions": [["0123456789ABCDEF", 3]]},
])
def test_unusable_saved_state_gives_an_empty_tracker_without_raising(state):
    tracker = Tracker.from_state(state)
    assert tracker.state()["sessions"] == []
    assert tracker.judge(packet(), NOW).fresh


def test_saved_state_keeps_the_good_entries_and_the_newest_when_too_long():
    sessions = [[f"{index:016x}", index + 1] for index in range(12)]
    restored = Tracker.from_state({"sessions": sessions}, remember=4)
    assert [entry[1] for entry in restored.state()["sessions"]] == [9, 10, 11, 12]
    mixed = Tracker.from_state({"sessions": [["0123456789abcdef", 3], ["bad", 1], ["fedcba9876543210", 4]]})
    assert len(mixed.state()["sessions"]) == 2


@pytest.mark.parametrize("options", [{"max_age": 0}, {"max_age": -1}, {"future_slack": -1}, {"remember": 0}])
def test_nonsense_limits_are_refused(options):
    with pytest.raises(ValueError):
        Tracker(**options)
