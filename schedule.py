"""Date- and local-time based browse scheduling, independent of the server timezone."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_WINDOW = re.compile(r'^(\d\d):(\d\d)-(\d\d):(\d\d)$')


def _parse_time(hour: str, minute: str) -> time:
    return time(int(hour), int(minute))


def local_day(now: datetime, timezone_name: str) -> date:
    if now.tzinfo is None: raise ValueError('current time must be timezone aware')
    if timezone_name == 'Asia/Shanghai':
        zone = timezone(timedelta(hours=8))
    else:
        try: zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError): raise ValueError('invalid timezone') from None
    return now.astimezone(zone).date()


def browse_allowed(now: datetime, *, timezone_name: str, windows: list[str],
                   start_date: str = '', end_date: str = '') -> bool:
    if now.tzinfo is None: raise ValueError('current time must be timezone aware')
    if timezone_name == 'Asia/Shanghai':
        zone = timezone(timedelta(hours=8))
    else:
        try: zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError): raise ValueError('invalid timezone') from None
    local = now.astimezone(zone)
    start = date.fromisoformat(start_date) if start_date else None
    end = date.fromisoformat(end_date) if end_date else None
    if start and end and start > end: raise ValueError('start date is after end date')
    parsed = []
    for item in windows:
        match = _WINDOW.fullmatch(item) if isinstance(item, str) else None
        if not match: raise ValueError('invalid browse time window')
        a = _parse_time(*match.groups()[:2])
        b = _parse_time(*match.groups()[2:])
        if a == b: raise ValueError('start and end times cannot match')
        parsed.append((a, b))
    # For an overnight window the after-midnight part belongs to its start date.
    tod = local.time().replace(tzinfo=None)
    periods = [(local.date(), True)] if not parsed else []
    for a, b in parsed:
        if a < b and a <= tod < b: periods.append((local.date(), True))
        elif a > b and tod >= a: periods.append((local.date(), True))
        elif a > b and tod < b: periods.append((local.date() - timedelta(days=1), True))
    return any((not start or day >= start) and (not end or day <= end) for day, _ in periods)
