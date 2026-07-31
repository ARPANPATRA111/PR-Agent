"""Timezone-safe recurrence calculations for durable public-v2 jobs."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from domain.errors import DomainError

UTC = timezone.utc


def as_utc(value: datetime) -> datetime:
    """Normalize database values; SQLite may return naive UTC datetimes."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_local_time(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise DomainError("Invalid scheduled local time.") from exc
    return parsed.replace(tzinfo=None)


def local_wall_time_to_utc(
    local_date: date,
    local_time: time,
    timezone_name: str,
) -> datetime:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise DomainError("Unknown IANA timezone.") from exc
    wall_time = datetime.combine(local_date, local_time)
    localized = wall_time.replace(tzinfo=zone, fold=0)
    utc_value = localized.astimezone(UTC)
    if utc_value.astimezone(zone).replace(tzinfo=None) != wall_time:
        raise DomainError("The scheduled local time does not exist.")
    return utc_value


def next_weekly_occurrence(
    *,
    timezone_name: str,
    weekday: int,
    scheduled_local_time: str,
    after_utc: datetime,
) -> datetime:
    """Return the first valid weekly wall-clock occurrence after ``after_utc``."""
    if weekday < 0 or weekday > 6:
        raise DomainError("Weekday must be between 0 and 6.")
    zone = ZoneInfo(timezone_name)
    after = as_utc(after_utc)
    local_after = after.astimezone(zone)
    candidate_date = local_after.date() + timedelta(
        days=(weekday - local_after.weekday()) % 7
    )
    local_time = parse_local_time(scheduled_local_time)

    for _ in range(3):
        try:
            candidate = local_wall_time_to_utc(
                candidate_date,
                local_time,
                timezone_name,
            )
        except DomainError:
            candidate_date += timedelta(days=7)
            continue
        if candidate > after:
            return candidate
        candidate_date += timedelta(days=7)
    raise DomainError("Unable to calculate the next weekly occurrence.")


def next_reminder_occurrence(reminder, after_utc: datetime) -> datetime | None:
    """Calculate the next recurring occurrence without schedule drift."""
    if reminder.schedule_type == "once":
        return None
    zone = ZoneInfo(reminder.timezone)
    after = as_utc(after_utc)
    local_after = after.astimezone(zone)
    local_time = parse_local_time(reminder.scheduled_local_time or "00:00:00")

    if reminder.schedule_type == "weekly":
        weekday = int((reminder.recurrence_rule or {}).get("weekday", 6))
        return next_weekly_occurrence(
            timezone_name=reminder.timezone,
            weekday=weekday,
            scheduled_local_time=local_time.isoformat(),
            after_utc=after,
        )

    candidate_date = local_after.date()
    for _ in range(4):
        try:
            candidate = local_wall_time_to_utc(
                candidate_date,
                local_time,
                reminder.timezone,
            )
        except DomainError:
            candidate_date += timedelta(days=1)
            continue
        if candidate > after:
            return candidate
        candidate_date += timedelta(days=1)
    raise DomainError("Unable to calculate the next daily occurrence.")
