import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from google.auth.exceptions import RefreshError

from calendars.sync_outlook_ics_to_google import SCOPES, google_calendar_service


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


if __name__ == "__main__":
    unittest.main()
