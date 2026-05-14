#!/usr/bin/env python3
"""One-way sync from an Outlook ICS feed into a Google Calendar."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
SYNC_SOURCE_KEY = "sakSyncSource"
SYNC_SOURCE_VALUE = "outlook-ics"
SYNC_HASH_KEY = "sakOutlookIcsHash"
DEFAULT_ICS_URL_FILE = Path(__file__).with_name("ics.txt")
DEFAULT_TIME_ZONE = "America/New_York"
WINDOWS_TIME_ZONE_MAP = {
    "Eastern Standard Time": "America/New_York",
    "Eastern Daylight Time": "America/New_York",
    "US Eastern Standard Time": "America/New_York",
    "US/Eastern": "America/New_York",
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Central Daylight Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver",
    "Mountain Daylight Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles",
    "Pacific Daylight Time": "America/Los_Angeles",
    "Alaskan Standard Time": "America/Anchorage",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "UTC": "UTC",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download an Outlook ICS feed and sync it into Google Calendar."
    )
    parser.add_argument("--ics-url", help="Outlook iCalendar .ics URL.")
    parser.add_argument(
        "--ics-url-file",
        default=str(DEFAULT_ICS_URL_FILE),
        help="Text file containing the Outlook iCalendar .ics URL.",
    )
    parser.add_argument(
        "--calendar-id",
        default="primary",
        help="Destination Google Calendar ID. Defaults to primary.",
    )
    parser.add_argument(
        "--credentials",
        default="credentials.json",
        help="OAuth client secrets JSON downloaded from Google Cloud.",
    )
    parser.add_argument(
        "--token",
        default="token.json",
        help="Where to store the local Google OAuth token.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Seconds to wait while downloading the ICS feed.",
    )
    parser.add_argument(
        "--time-zone",
        default=DEFAULT_TIME_ZONE,
        help="Timezone to use for ICS date-times that do not include one.",
    )
    parser.add_argument(
        "--delete-missing",
        action="store_true",
        help="Delete synced Google events that are no longer present in the Outlook feed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to Google Calendar.",
    )
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="Authorize Google Calendar access, then exit without downloading or syncing events.",
    )
    return parser.parse_args()


def google_calendar_service(credentials_path: Path, token_path: Path) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"Missing Google OAuth client file: {credentials_path}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=creds)


def download_ics(ics_url: str, timeout: int) -> bytes:
    request = urllib.request.Request(ics_url, headers={"User-Agent": "SAK calendar sync"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def resolve_ics_url(ics_url: str | None, ics_url_file: str) -> str:
    if ics_url:
        return ics_url.strip()

    path = Path(ics_url_file)
    if not path.exists():
        raise FileNotFoundError(
            f"Missing ICS URL. Pass --ics-url or create {path} with the Outlook ICS URL."
        )

    url = path.read_text(encoding="utf-8").strip()
    if not url:
        raise ValueError(f"ICS URL file is empty: {path}")
    return url


def validate_time_zone(time_zone: str) -> str:
    try:
        ZoneInfo(time_zone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {time_zone}") from exc
    return time_zone


def google_time_zone(time_zone: Any, default_time_zone: str) -> str:
    candidate = str(time_zone or "").strip().strip('"')
    if candidate.lower().startswith("tzone://microsoft/"):
        candidate = candidate.rsplit("/", 1)[-1]
    candidate = WINDOWS_TIME_ZONE_MAP.get(candidate, candidate)
    candidate = WINDOWS_TIME_ZONE_MAP.get(candidate.title(), candidate)
    candidate = candidate.removeprefix("/")

    if not candidate:
        return default_time_zone

    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError:
        return default_time_zone
    return candidate


def text_value(component: Any, name: str) -> str | None:
    value = component.get(name)
    if value is None:
        return None
    return str(value)


def datetime_value(value: Any, default_time_zone: str) -> dict[str, str]:
    decoded = value.dt
    if isinstance(decoded, dt.datetime):
        date_time = decoded.isoformat()
        body = {"dateTime": date_time}
        tzid = value.params.get("TZID")
        if tzid:
            body["timeZone"] = google_time_zone(tzid, default_time_zone)
        elif decoded.tzinfo is None or decoded.utcoffset() is None or not has_utc_offset(date_time):
            body["timeZone"] = default_time_zone
        return body
    if isinstance(decoded, dt.date):
        return {"date": decoded.isoformat()}
    raise ValueError(f"Unsupported calendar date value: {decoded!r}")


def has_utc_offset(date_time: str) -> bool:
    time_part = date_time.split("T", 1)[-1]
    return time_part.endswith("Z") or "+" in time_part or "-" in time_part


def add_missing_time_zone(
    event_time: dict[str, str],
    default_time_zone: str,
    always_for_timed_event: bool = False,
) -> None:
    date_time = event_time.get("dateTime")
    if not date_time:
        return

    if "timeZone" in event_time:
        event_time["timeZone"] = google_time_zone(event_time["timeZone"], default_time_zone)
    elif always_for_timed_event or not has_utc_offset(date_time):
        event_time["timeZone"] = default_time_zone


def property_lines(component: Any, name: str, default_time_zone: str) -> list[str]:
    value = component.get(name)
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    lines = []
    for item in values:
        params = "".join(
            f";{key}={google_time_zone(val, default_time_zone) if key == 'TZID' else val}"
            for key, val in item.params.items()
        )
        lines.append(f"{name}{params}:{item.to_ical().decode('utf-8')}")
    return lines


def recurrence_lines(component: Any, default_time_zone: str) -> list[str]:
    lines: list[str] = []
    for name in ("RRULE", "RDATE", "EXDATE"):
        lines.extend(property_lines(component, name, default_time_zone))
    return lines


def event_fingerprint(event: dict[str, Any]) -> str:
    payload = {
        key: event.get(key)
        for key in (
            "summary",
            "description",
            "location",
            "start",
            "end",
            "recurrence",
            "transparency",
            "visibility",
            "status",
        )
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def google_event_from_ics(component: Any, default_time_zone: str) -> dict[str, Any] | None:
    uid = text_value(component, "UID")
    start = component.get("DTSTART")
    end = component.get("DTEND")
    duration = component.get("DURATION")

    if not uid or start is None:
        return None

    if component.get("RECURRENCE-ID") is not None:
        print(f"Skipping recurrence exception for UID {uid}; standalone exceptions need manual review.")
        return None

    event: dict[str, Any] = {
        "iCalUID": uid,
        "summary": text_value(component, "SUMMARY") or "(No title)",
        "start": datetime_value(start, default_time_zone),
        "extendedProperties": {
            "private": {
                SYNC_SOURCE_KEY: SYNC_SOURCE_VALUE,
            }
        },
    }

    if end is not None:
        event["end"] = datetime_value(end, default_time_zone)
    elif duration is not None:
        started = start.dt
        if isinstance(started, dt.datetime):
            event["end"] = {"dateTime": (started + duration.dt).isoformat()}
            if started.tzinfo is None:
                event["end"]["timeZone"] = event["start"].get("timeZone", default_time_zone)
        elif isinstance(started, dt.date):
            event["end"] = {"date": (started + duration.dt).isoformat()}
    else:
        started = start.dt
        if isinstance(started, dt.datetime):
            event["end"] = {"dateTime": (started + dt.timedelta(hours=1)).isoformat()}
            if started.tzinfo is None:
                event["end"]["timeZone"] = event["start"].get("timeZone", default_time_zone)
        elif isinstance(started, dt.date):
            event["end"] = {"date": (started + dt.timedelta(days=1)).isoformat()}

    for ics_name, google_name in (
        ("DESCRIPTION", "description"),
        ("LOCATION", "location"),
        ("STATUS", "status"),
    ):
        value = text_value(component, ics_name)
        if value:
            event[google_name] = value.lower() if google_name == "status" else value

    if str(component.get("TRANSP")).upper() == "TRANSPARENT":
        event["transparency"] = "transparent"

    recurrence = recurrence_lines(component, default_time_zone)
    if recurrence:
        event["recurrence"] = recurrence

    is_recurring = bool(event.get("recurrence"))
    add_missing_time_zone(event["start"], default_time_zone, is_recurring)
    add_missing_time_zone(event["end"], default_time_zone, is_recurring)
    event["extendedProperties"]["private"][SYNC_HASH_KEY] = event_fingerprint(event)
    return event


def outlook_events(ics_bytes: bytes, default_time_zone: str) -> list[dict[str, Any]]:
    from icalendar import Calendar

    calendar = Calendar.from_ical(ics_bytes)
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    for component in calendar.walk("VEVENT"):
        event = google_event_from_ics(component, default_time_zone)
        if not event:
            continue
        uid = event["iCalUID"]
        if uid in seen:
            print(f"Skipping duplicate UID in ICS feed: {uid}")
            continue
        seen.add(uid)
        events.append(event)

    return events


def find_google_event(service: Any, calendar_id: str, ical_uid: str) -> dict[str, Any] | None:
    result = (
        service.events()
        .list(calendarId=calendar_id, iCalUID=ical_uid, maxResults=1, showDeleted=False)
        .execute()
    )
    items = result.get("items", [])
    return items[0] if items else None


def list_synced_google_events(service: Any, calendar_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    page_token = None
    while True:
        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                privateExtendedProperty=f"{SYNC_SOURCE_KEY}={SYNC_SOURCE_VALUE}",
                showDeleted=False,
                pageToken=page_token,
            )
            .execute()
        )
        events.extend(result.get("items", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            return events


def sync_event(service: Any, calendar_id: str, event: dict[str, Any], dry_run: bool) -> str:
    existing = find_google_event(service, calendar_id, event["iCalUID"])
    new_hash = event["extendedProperties"]["private"][SYNC_HASH_KEY]

    if existing is None:
        if not dry_run:
            service.events().import_(calendarId=calendar_id, body=event).execute()
        return "created"

    old_hash = (
        existing.get("extendedProperties", {})
        .get("private", {})
        .get(SYNC_HASH_KEY)
    )
    if old_hash == new_hash:
        return "unchanged"

    event_id = existing["id"]
    update_body = dict(event)
    update_body.pop("iCalUID", None)
    if not dry_run:
        service.events().update(calendarId=calendar_id, eventId=event_id, body=update_body).execute()
    return "updated"


def delete_missing_events(
    service: Any,
    calendar_id: str,
    current_uids: set[str],
    dry_run: bool,
) -> int:
    deleted = 0
    for event in list_synced_google_events(service, calendar_id):
        uid = event.get("iCalUID")
        if uid and uid not in current_uids:
            deleted += 1
            if not dry_run:
                service.events().delete(calendarId=calendar_id, eventId=event["id"]).execute()
    return deleted


def main() -> int:
    args = parse_args()
    try:
        if args.auth_only:
            google_calendar_service(Path(args.credentials), Path(args.token))
            print(f"Google Calendar credentials are ready. Token saved to {args.token}.")
            return 0

        ics_url = resolve_ics_url(args.ics_url, args.ics_url_file)
        time_zone = validate_time_zone(args.time_zone)
        ics_bytes = download_ics(ics_url, args.timeout)
        events = outlook_events(ics_bytes, time_zone)
        service = google_calendar_service(Path(args.credentials), Path(args.token))

        counts = {"created": 0, "updated": 0, "unchanged": 0}
        for event in events:
            result = sync_event(service, args.calendar_id, event, args.dry_run)
            counts[result] += 1

        deleted = 0
        if args.delete_missing:
            deleted = delete_missing_events(
                service,
                args.calendar_id,
                {event["iCalUID"] for event in events},
                args.dry_run,
            )

        prefix = "Dry run: " if args.dry_run else ""
        print(
            f"{prefix}{len(events)} Outlook events processed; "
            f"{counts['created']} created, {counts['updated']} updated, "
            f"{counts['unchanged']} unchanged, {deleted} deleted."
        )
        return 0
    except Exception as exc:
        print(f"Sync failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
