import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from google.auth.exceptions import RefreshError

from calendars.sync_outlook_ics_to_google import (
    SCOPES,
    SYNC_SOURCE_KEY,
    SYNC_SOURCE_VALUE,
    google_calendar_service,
    sync_event,
)


class GoogleCalendarAuthenticationTests(unittest.TestCase):
    def test_invalid_saved_token_starts_fresh_authorization(self) -> None:
        stale_credentials = Mock(
            valid=False,
            expired=True,
            refresh_token="stale-refresh-token",
        )
        stale_credentials.refresh.side_effect = RefreshError(
            "invalid_grant: Bad Request",
            {"error": "invalid_grant", "error_description": "Bad Request"},
        )

        fresh_credentials = Mock(valid=True)
        fresh_credentials.to_json.return_value = '{"token": "fresh"}'
        flow = Mock()
        flow.run_local_server.return_value = fresh_credentials
        service = Mock()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            credentials_path = root / "credentials.json"
            token_path = root / "token.json"
            credentials_path.write_text("{}", encoding="utf-8")
            token_path.write_text("{}", encoding="utf-8")

            with (
                patch(
                    "google.oauth2.credentials.Credentials.from_authorized_user_file",
                    return_value=stale_credentials,
                ),
                patch(
                    "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                    return_value=flow,
                ) as create_flow,
                patch("googleapiclient.discovery.build", return_value=service),
            ):
                result = google_calendar_service(credentials_path, token_path)

            self.assertIs(result, service)
            stale_credentials.refresh.assert_called_once()
            create_flow.assert_called_once_with(str(credentials_path), SCOPES)
            flow.run_local_server.assert_called_once_with(port=0)
            self.assertEqual(token_path.read_text(encoding="utf-8"), '{"token": "fresh"}')


class GoogleCalendarEventSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = Mock()
        self.events_resource = self.service.events.return_value
        self.event = {
            "iCalUID": "outlook-event-uid",
            "summary": "Dept. Chairs & Faculty Director Meeting",
            "start": {"dateTime": "2026-09-10T12:30:00-04:00"},
            "end": {"dateTime": "2026-09-10T13:45:00-04:00"},
            "extendedProperties": {
                "private": {
                    SYNC_SOURCE_KEY: SYNC_SOURCE_VALUE,
                    "sakOutlookIcsHash": "new-hash",
                }
            },
        }

    def test_existing_event_not_created_by_sync_is_skipped(self) -> None:
        self.events_resource.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "foreign-google-event",
                    "iCalUID": self.event["iCalUID"],
                    "summary": "Existing invitation",
                }
            ]
        }

        with patch("builtins.print") as print_message:
            result = sync_event(self.service, "primary", self.event, dry_run=False)

        self.assertEqual(result, "skipped")
        self.events_resource.update.assert_not_called()
        self.events_resource.import_.assert_not_called()
        self.assertIn("not created by this sync", print_message.call_args.args[0])

    def test_existing_event_created_by_sync_can_be_updated(self) -> None:
        self.events_resource.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "sak-google-event",
                    "iCalUID": self.event["iCalUID"],
                    "extendedProperties": {
                        "private": {
                            SYNC_SOURCE_KEY: SYNC_SOURCE_VALUE,
                            "sakOutlookIcsHash": "old-hash",
                        }
                    },
                }
            ]
        }

        result = sync_event(self.service, "primary", self.event, dry_run=False)

        self.assertEqual(result, "updated")
        update_call = self.events_resource.update.call_args
        self.assertEqual(update_call.kwargs["calendarId"], "primary")
        self.assertEqual(update_call.kwargs["eventId"], "sak-google-event")
        self.assertNotIn("iCalUID", update_call.kwargs["body"])
        update_call.return_value.execute.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
