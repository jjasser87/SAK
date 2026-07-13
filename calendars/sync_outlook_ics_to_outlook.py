#!/usr/bin/env python3
"""One-way sync from an Outlook ICS feed into a personal Outlook calendar via Microsoft Graph API.

Setup (one-time):
1. Go to https://portal.azure.com → Azure Active Directory → App registrations → New registration.
2. Name it (e.g. "SAK Calendar Sync"), select "Personal Microsoft accounts only", click Register.
3. Under "Authentication" → "Advanced settings", enable "Allow public client flows".
4. Under "API permissions" add a Delegated permission: Microsoft Graph → Calendars.ReadWrite.
5. Copy the Application (client) ID and save it to ms_credentials.json:
       {"client_id": "YOUR-CLIENT-ID-HERE"}
6. Run this script; it will prompt you to sign in once via a device code.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
AUTHORITY = "https://login.microsoftonline.com/consumers"
SCOPES = ["Calendars.ReadWrite"]

# Extended-property IDs used to tag events created by this script.
_EP_GUID = "A9B7C8D6-E5F4-4321-8765-ABCDEF012345"
SYNC_SOURCE_PROP_ID = f"String {{{_EP_GUID}}} Name sakSyncSource"
SYNC_HASH_PROP_ID = f"String {{{_EP_GUID}}} Name sakOutlookIcsHash"
SYNC_UID_PROP_ID = f"String {{{_EP_GUID}}} Name sakICalUID"
SYNC_SOURCE_VALUE = "outlook-ics"

_EP_EXPAND = (
    f"singleValueExtendedProperties($filter="
    f"id eq '{SYNC_SOURCE_PROP_ID}' or "
    f"id eq '{SYNC_HASH_PROP_ID}' or "
    f"id eq '{SYNC_UID_PROP_ID}')"
)
_EP_FILTER = (
    f"singleValueExtendedProperties/Any(ep: ep/id eq '{SYNC_SOURCE_PROP_ID}' "
    f"and ep/value eq '{SYNC_SOURCE_VALUE}')"
)

DEFAULT_ICS_URL_FILE = Path(__file__).with_name("ics.txt")
DEFAULT_MS_CREDS_FILE = Path(__file__).with_name("ms_credentials.json")
DEFAULT_TOKEN_CACHE_FILE = Path(__file__).with_name("ms_token_cache.json")
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download an Outlook ICS feed and sync it into a personal Outlook calendar."
    )
    parser.add_argument("--ics-url", help="Outlook iCalendar .ics URL.")
    parser.add_argument(
        "--ics-url-file",
        default=str(DEFAULT_ICS_URL_FILE),
        help="Text file containing the Outlook iCalendar .ics URL.",
    )
    parser.add_argument(
        "--calendar-id",
        default=None,
        help="Destination Outlook calendar ID. Defaults to the primary calendar.",
    )
    parser.add_argument(
        "--credentials",
        default=str(DEFAULT_MS_CREDS_FILE),
        help="JSON file containing the Azure app client_id.",
    )
    parser.add_argument(
        "--token-cache",
        default=str(DEFAULT_TOKEN_CACHE_FILE),
        help="Where to store the local MSAL token cache.",
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
        help="Timezone for ICS date-times that do not include one.",
    )
    parser.add_argument(
        "--delete-missing",
        action="store_true",
        help="Delete synced Outlook events no longer present in the ICS feed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to Outlook.",
    )
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="Authorize Outlook access, then exit without syncing.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Authentication (MSAL)
# ---------------------------------------------------------------------------

def load_client_id(credentials_path: Path) -> str:
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"Missing Azure credentials file: {credentials_path}\n"
            "Create it with: {\"client_id\": \"YOUR-AZURE-APP-CLIENT-ID\"}"
        )
    data = json.loads(credentials_path.read_text(encoding="utf-8"))
    client_id = data.get("client_id", "").strip()
    if not client_id:
        raise ValueError(f"'client_id' is missing or empty in {credentials_path}")
    return client_id


def authenticate(client_id: str, cache_path: Path) -> tuple[str, Any]:
    """Return (access_token, msal_app). Call save_token_cache() after the sync."""
    from msal import PublicClientApplication, SerializableTokenCache

    cache = SerializableTokenCache()
    if cache_path.exists():
        cache.deserialize(cache_path.read_text(encoding="utf-8"))

    app = PublicClientApplication(client_id, authority=AUTHORITY, token_cache=cache)

    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(
                f"Device flow initiation failed: {flow.get('error_description', flow)}"
            )
        print(flow["message"])
        sys.stdout.flush()
        result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise RuntimeError(
            f"Authentication failed: {result.get('error_description', result)}"
        )

    if cache.has_state_changed:
        cache_path.write_text(cache.serialize(), encoding="utf-8")

    return result["access_token"], app, cache


def save_token_cache(app: Any, cache: Any, cache_path: Path) -> None:
    if cache.has_state_changed:
        cache_path.write_text(cache.serialize(), encoding="utf-8")


# ---------------------------------------------------------------------------
# Microsoft Graph helpers
# ---------------------------------------------------------------------------

def graph_request(
    access_token: str,
    method: str,
    path: str,
    body: dict | None = None,
    params: dict[str, str] | None = None,
) -> dict | None:
    url = f"{GRAPH_BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    data = json.dumps(body).encode("utf-8") if body else None
    headers: dict[str, str] = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    if data:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status in (204, 201) and not resp.length:
                return None
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Graph API {method} {path} failed ({exc.code}): {error_body}"
        ) from exc


def graph_get_all(access_token: str, path: str, params: dict[str, str]) -> list[dict]:
    """Fetch all pages from a Graph API list endpoint."""
    items: list[dict] = []
    url: str | None = f"{GRAPH_BASE}{path}?{urllib.parse.urlencode(params)}"
    while url:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req) as resp:
                page = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Graph API GET {url} failed ({exc.code}): {error_body}"
            ) from exc
        items.extend(page.get("value", []))
        url = page.get("@odata.nextLink")
    return items


def calendar_path(calendar_id: str | None) -> str:
    if calendar_id:
        return f"/me/calendars/{calendar_id}/events"
    return "/me/events"


# ---------------------------------------------------------------------------
# ICS download and URL resolution
# ---------------------------------------------------------------------------

def download_ics(ics_url: str, timeout: int) -> bytes:
    req = urllib.request.Request(ics_url, headers={"User-Agent": "SAK calendar sync"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


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


# ---------------------------------------------------------------------------
# Timezone helpers
# ---------------------------------------------------------------------------

def validate_time_zone(time_zone: str) -> str:
    try:
        ZoneInfo(time_zone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {time_zone}") from exc
    return time_zone


def iana_time_zone(raw: Any, default_time_zone: str) -> str:
    candidate = str(raw or "").strip().strip('"')
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


# ---------------------------------------------------------------------------
# ICS → Graph API event conversion
# ---------------------------------------------------------------------------

def text_value(component: Any, name: str) -> str | None:
    value = component.get(name)
    return str(value) if value is not None else None


def graph_datetime_body(value: Any, default_time_zone: str) -> dict[str, str]:
    decoded = value.dt
    if isinstance(decoded, dt.datetime):
        tzid = value.params.get("TZID")
        tz = iana_time_zone(tzid, default_time_zone) if tzid else default_time_zone
        if decoded.tzinfo is not None and decoded.utcoffset() is not None:
            decoded = decoded.astimezone(ZoneInfo(tz)).replace(tzinfo=None)
        return {"dateTime": decoded.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz}
    raise ValueError(f"Expected datetime, got: {decoded!r}")


def event_fingerprint(data: dict[str, Any]) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def graph_event_from_ics(
    component: Any, default_time_zone: str
) -> tuple[dict[str, Any], str, str] | None:
    """Return (graph_event_body, ical_uid, content_hash) or None to skip."""
    uid = text_value(component, "UID")
    start = component.get("DTSTART")

    if not uid or start is None:
        return None

    if component.get("RECURRENCE-ID") is not None:
        print(f"  Skipping recurrence exception for UID {uid}")
        return None

    if component.get("RRULE") is not None:
        print(f"  Skipping recurring event (UID {uid}): recurrence translation not supported")
        return None

    start_dt = start.dt
    is_all_day = isinstance(start_dt, dt.date) and not isinstance(start_dt, dt.datetime)

    event: dict[str, Any] = {
        "subject": text_value(component, "SUMMARY") or "(No title)",
        "isAllDay": is_all_day,
    }

    end = component.get("DTEND")
    duration = component.get("DURATION")

    if is_all_day:
        event["start"] = {"dateTime": start_dt.strftime("%Y-%m-%dT00:00:00"), "timeZone": "UTC"}
        if end is not None:
            end_dt = end.dt
            event["end"] = {"dateTime": end_dt.strftime("%Y-%m-%dT00:00:00"), "timeZone": "UTC"}
        else:
            next_day = start_dt + dt.timedelta(days=1)
            event["end"] = {"dateTime": next_day.strftime("%Y-%m-%dT00:00:00"), "timeZone": "UTC"}
    else:
        event["start"] = graph_datetime_body(start, default_time_zone)
        tz = event["start"]["timeZone"]
        if end is not None:
            event["end"] = graph_datetime_body(end, default_time_zone)
        elif duration is not None:
            end_dt_raw = start_dt + duration.dt
            if isinstance(end_dt_raw, dt.datetime):
                end_dt_raw = end_dt_raw.astimezone(ZoneInfo(tz)).replace(tzinfo=None)
            event["end"] = {"dateTime": end_dt_raw.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz}
        else:
            end_dt_raw = start_dt + dt.timedelta(hours=1)
            if isinstance(end_dt_raw, dt.datetime):
                end_dt_raw = end_dt_raw.replace(tzinfo=None)
            event["end"] = {"dateTime": end_dt_raw.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz}

    description = text_value(component, "DESCRIPTION")
    if description:
        event["body"] = {"contentType": "text", "content": description}

    location = text_value(component, "LOCATION")
    if location:
        event["location"] = {"displayName": location}

    transp = str(component.get("TRANSP") or "").upper()
    if transp == "TRANSPARENT":
        event["showAs"] = "free"

    fingerprint_keys = ("subject", "start", "end", "body", "location", "isAllDay", "showAs")
    content_hash = event_fingerprint({k: event.get(k) for k in fingerprint_keys})

    event["singleValueExtendedProperties"] = [
        {"id": SYNC_SOURCE_PROP_ID, "value": SYNC_SOURCE_VALUE},
        {"id": SYNC_UID_PROP_ID, "value": uid},
        {"id": SYNC_HASH_PROP_ID, "value": content_hash},
    ]

    return event, uid, content_hash


def parse_outlook_events(
    ics_bytes: bytes, default_time_zone: str
) -> list[tuple[dict[str, Any], str, str]]:
    from icalendar import Calendar

    calendar = Calendar.from_ical(ics_bytes)
    events: list[tuple[dict[str, Any], str, str]] = []
    seen: set[str] = set()

    for component in calendar.walk("VEVENT"):
        result = graph_event_from_ics(component, default_time_zone)
        if result is None:
            continue
        event, uid, content_hash = result
        if uid in seen:
            print(f"  Skipping duplicate UID in ICS feed: {uid}")
            continue
        seen.add(uid)
        events.append((event, uid, content_hash))

    return events


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------

def _extended_prop_value(event: dict, prop_id: str) -> str | None:
    for ep in event.get("singleValueExtendedProperties") or []:
        if ep.get("id") == prop_id:
            return ep.get("value")
    return None


def find_outlook_event(
    access_token: str, cal_path: str, ical_uid: str
) -> dict | None:
    ep_filter = (
        f"singleValueExtendedProperties/Any(ep: ep/id eq '{SYNC_UID_PROP_ID}' "
        f"and ep/value eq '{ical_uid}')"
    )
    items = graph_get_all(
        access_token,
        cal_path,
        {
            "$filter": ep_filter,
            "$expand": _EP_EXPAND,
            "$top": "1",
        },
    )
    return items[0] if items else None


def list_synced_events(access_token: str, cal_path: str) -> list[dict]:
    return graph_get_all(
        access_token,
        cal_path,
        {
            "$filter": _EP_FILTER,
            "$expand": _EP_EXPAND,
            "$select": "id,iCalUId,singleValueExtendedProperties",
        },
    )


def sync_event(
    access_token: str,
    cal_path: str,
    event: dict[str, Any],
    ical_uid: str,
    content_hash: str,
    dry_run: bool,
) -> str:
    existing = find_outlook_event(access_token, cal_path, ical_uid)

    if existing is None:
        if not dry_run:
            graph_request(access_token, "POST", cal_path, body=event)
        return "created"

    old_hash = _extended_prop_value(existing, SYNC_HASH_PROP_ID)
    if old_hash == content_hash:
        return "unchanged"

    event_id = existing["id"]
    update_path = f"{cal_path}/{event_id}"
    if not dry_run:
        graph_request(access_token, "PATCH", update_path, body=event)
    return "updated"


def delete_missing_events(
    access_token: str,
    cal_path: str,
    current_uids: set[str],
    dry_run: bool,
) -> int:
    deleted = 0
    for event in list_synced_events(access_token, cal_path):
        uid = _extended_prop_value(event, SYNC_UID_PROP_ID)
        if uid and uid not in current_uids:
            deleted += 1
            if not dry_run:
                graph_request(access_token, "DELETE", f"{cal_path}/{event['id']}")
    return deleted


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    try:
        client_id = load_client_id(Path(args.credentials))
        access_token, app, cache = authenticate(client_id, Path(args.token_cache))

        if args.auth_only:
            save_token_cache(app, cache, Path(args.token_cache))
            print(f"Outlook credentials are ready. Token cache saved to {args.token_cache}.")
            return 0

        ics_url = resolve_ics_url(args.ics_url, args.ics_url_file)
        time_zone = validate_time_zone(args.time_zone)
        ics_bytes = download_ics(ics_url, args.timeout)
        events = parse_outlook_events(ics_bytes, time_zone)

        cal_path = calendar_path(args.calendar_id)
        counts = {"created": 0, "updated": 0, "unchanged": 0}
        for event, uid, content_hash in events:
            result = sync_event(access_token, cal_path, event, uid, content_hash, args.dry_run)
            counts[result] += 1

        deleted = 0
        if args.delete_missing:
            current_uids = {uid for _, uid, _ in events}
            deleted = delete_missing_events(access_token, cal_path, current_uids, args.dry_run)

        save_token_cache(app, cache, Path(args.token_cache))

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
