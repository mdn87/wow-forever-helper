"""Explicit local reset rules and append-only manual completion events."""

from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .chat import ChatError

MAX_EVENTS = 2000
DAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')


def validate_rule(rule):
    try:
        if (not isinstance(rule, dict) or set(rule) != {'frequency', 'zone', 'time', 'weekday'}
                or rule['frequency'] not in ('Daily', 'Weekly')
                or not isinstance(rule['zone'], str) or len(rule['zone']) > 100
                or not isinstance(rule['time'], str) or not re.fullmatch(r'\d{2}:\d{2}', rule['time'])
                or type(rule['weekday']) is not int or not 0 <= rule['weekday'] <= 6):
            raise ValueError
        if int(rule['time'][:2]) > 23 or int(rule['time'][3:]) > 59:
            raise ValueError
        time.fromisoformat(rule['time'])
        ZoneInfo(rule['zone'])
        return deepcopy(rule)
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise ChatError('Choose Daily or Weekly, an installed IANA time zone (for example America/New_York), '
                        'a reset time in HH:MM, and a weekday. Install the chat dependencies if time zones are unavailable.') from None


def period(rule, now=None):
    """Return reset-date identity. Fold uses the first occurrence; gaps shift forward.

    Compare UTC instants, not local wall times, so a repeated hour cannot reopen
    yesterday. Re-reading after a clock change never rewrites saved history.
    """
    rule = validate_rule(rule)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ChatError('The checklist clock must include a time zone.')
    instant = now.astimezone(timezone.utc)
    zone = ZoneInfo(rule['zone'])
    day = instant.astimezone(zone).date()
    step = 1 if rule['frequency'] == 'Daily' else 7
    if step == 7:
        day -= timedelta(days=(day.weekday() - rule['weekday']) % 7)
    boundary = datetime.combine(day, time.fromisoformat(rule['time']), zone).astimezone(timezone.utc)
    if instant < boundary:
        day -= timedelta(days=step)
    return day.isoformat()


def validate_events(events):
    try:
        if not isinstance(events, list) or len(events) > MAX_EVENTS:
            raise ValueError
        for event in events:
            if not isinstance(event, dict) or set(event) != {'rule', 'period', 'done', 'at'}:
                raise ValueError
            validate_rule(event['rule'])
            if type(event['done']) is not bool:
                raise ValueError
            from datetime import date
            if date.fromisoformat(event['period']).isoformat() != event['period']:
                raise ValueError
            if datetime.fromisoformat(event['at']).tzinfo is None:
                raise ValueError
        return deepcopy(events)
    except (ValueError, TypeError, KeyError):
        raise ChatError('The checklist history is invalid. Existing data has been kept.') from None


def completed(entry, rule, current_period):
    return next((event['done'] for event in reversed(entry.get('completions', []))
                 if event['rule'] == rule and event['period'] == current_period), False)


def rule_summary(rule):
    return (rule['frequency'] + ' at ' + rule['time'] + ' ' + rule['zone'] +
            (' on ' + DAYS[rule['weekday']] if rule['frequency'] == 'Weekly' else ''))
