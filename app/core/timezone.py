"""Timezone helpers for the Lads Beer system.

All datetimes are stored in UTC in the database. Business reports and UI
displays use the Brasília timezone (America/Sao_Paulo).
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def now_local() -> datetime:
    """Current datetime in Brasília time."""
    return datetime.now(LOCAL_TIMEZONE)


def today_local() -> date:
    """Current date in Brasília time."""
    return now_local().date()


def as_local(dt: datetime | None) -> datetime | None:
    """Convert a UTC or naive datetime to Brasília time."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TIMEZONE)


def local_date(dt: datetime) -> date:
    """Return the Brasília date for a given datetime."""
    return as_local(dt).date()


def local_date_str(dt: datetime) -> str:
    """Return 'YYYY-MM-DD' in Brasília time."""
    return as_local(dt).strftime("%Y-%m-%d")


def local_hour_label(dt: datetime) -> str:
    """Return 'HH:00' in Brasília time."""
    return as_local(dt).strftime("%H:00")


def local_datetime_str(dt: datetime) -> str:
    """Return 'DD/MM/YYYY HH:MM' in Brasília time."""
    return as_local(dt).strftime("%d/%m/%Y %H:%M")


def start_of_day_local(d: date) -> datetime:
    """Return the start of a local date as an aware Brasília datetime."""
    return datetime.combine(d, time.min, tzinfo=LOCAL_TIMEZONE)


def end_of_day_local(d: date) -> datetime:
    """Return the end of a local date as an aware Brasília datetime."""
    return datetime.combine(d, time.max, tzinfo=LOCAL_TIMEZONE)


def local_day_to_utc_range(d: date) -> tuple[datetime, datetime]:
    """Return the UTC range that corresponds to a local calendar day."""
    start = start_of_day_local(d).astimezone(timezone.utc)
    end = end_of_day_local(d).astimezone(timezone.utc)
    return start, end


def parse_local_date(value: str | None) -> date | None:
    """Parse a 'YYYY-MM-DD' string as a local date."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_local_date_range(
    start_str: str | None,
    end_str: str | None,
    default_days: int = 1,
) -> tuple[datetime, datetime, date, date]:
    """Return UTC and local date ranges from 'YYYY-MM-DD' inputs.

    The returned tuple is: (start_utc, end_utc, start_local, end_local).
    """
    today = today_local()
    start_local = parse_local_date(start_str) or (today - timedelta(days=default_days - 1))
    end_local = parse_local_date(end_str) or today

    start_utc, _ = local_day_to_utc_range(start_local)
    _, end_utc = local_day_to_utc_range(end_local)
    return start_utc, end_utc, start_local, end_local


def parse_local_datetime(value: str | None) -> datetime | None:
    """Parse a datetime string as a local Brasília datetime.

    If the string has no timezone, it is treated as local time. If it already
    has an offset, it is converted to Brasília time.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TIMEZONE)
    return dt.astimezone(LOCAL_TIMEZONE)


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Convert a local or naive datetime to UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TIMEZONE)
    return dt.astimezone(timezone.utc)


def format_local_date(d: date) -> str:
    """Return 'DD/MM/YYYY'."""
    return d.strftime("%d/%m/%Y")


def format_local_period(start_utc: datetime, end_utc: datetime) -> str:
    """Return a user-friendly period string in Brasília time."""
    start = as_local(start_utc)
    end = as_local(end_utc)
    if start.date() == end.date():
        return f"{start.strftime('%d/%m/%Y')} {start.strftime('%H:%M')} - {end.strftime('%H:%M')}"
    return f"{start.strftime('%d/%m/%Y')} - {end.strftime('%d/%m/%Y')}"
