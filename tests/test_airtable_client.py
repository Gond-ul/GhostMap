"""
Unit tests for the Airtable Metadata API client methods on
AirtableToPostgres: get_all_workspaces and get_base_schema.

The Airtable HTTP layer is mocked via unittest.mock.patch on
airtable_to_postgres.requests.get, so these tests run offline with no
real Airtable token, network access, or database.

Testing pagination inside sync_table_data would require also mocking
the PostgreSQL cursor/connection, which is a different concern (DB
I/O, not the Airtable client) -- that is intentionally out of scope
here.
"""

import os

os.environ["AIRTABLE_TOKEN"] = "test-token"

from unittest.mock import MagicMock, patch

from airtable_to_postgres import AirtableToPostgres


def _mock_response(json_data, status_code=200):
    """Build a mock requests.Response that behaves like a successful call."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status.return_value = None
    return mock_resp


class TestGetAllWorkspaces:
    @patch("airtable_to_postgres.time.sleep")  # skip the real rate-limit delay
    @patch("airtable_to_postgres.requests.get")
    def test_returns_parsed_workspaces_list(self, mock_get, mock_sleep):
        payload = {
            "workspaces": [
                {"id": "wspABC123", "name": "Marketing"},
                {"id": "wspDEF456", "name": "Engineering"},
            ]
        }
        mock_get.return_value = _mock_response(payload)

        syncer = AirtableToPostgres()
        workspaces = syncer.get_all_workspaces()

        assert workspaces == payload["workspaces"]
        assert len(workspaces) == 2
        assert workspaces[0]["name"] == "Marketing"

    @patch("airtable_to_postgres.time.sleep")
    @patch("airtable_to_postgres.requests.get")
    def test_calls_correct_endpoint_with_auth_header(self, mock_get, mock_sleep):
        mock_get.return_value = _mock_response({"workspaces": []})

        syncer = AirtableToPostgres()
        syncer.get_all_workspaces()

        mock_get.assert_called_once_with(
            "https://api.airtable.com/v0/meta/workspaces",
            headers={"Authorization": "Bearer test-token"},
        )

    @patch("airtable_to_postgres.time.sleep")
    @patch("airtable_to_postgres.requests.get")
    def test_raises_when_request_fails(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("503 Service Unavailable")
        mock_get.return_value = mock_resp

        syncer = AirtableToPostgres()
        try:
            syncer.get_all_workspaces()
            assert False, "expected an exception to propagate"
        except Exception as exc:
            assert "503" in str(exc)


class TestGetBaseSchema:
    @patch("airtable_to_postgres.time.sleep")
    @patch("airtable_to_postgres.requests.get")
    def test_returns_schema_dict_with_tables(self, mock_get, mock_sleep):
        payload = {
            "tables": [
                {
                    "id": "tblXYZ789",
                    "name": "Contacts",
                    "fields": [
                        {"id": "fld1", "name": "Name", "type": "singleLineText"},
                        {"id": "fld2", "name": "Signed Up", "type": "dateTime"},
                    ],
                }
            ]
        }
        mock_get.return_value = _mock_response(payload)

        syncer = AirtableToPostgres()
        schema = syncer.get_base_schema("appBASE123")

        assert schema == payload
        assert schema["tables"][0]["name"] == "Contacts"
        assert len(schema["tables"][0]["fields"]) == 2

    @patch("airtable_to_postgres.time.sleep")
    @patch("airtable_to_postgres.requests.get")
    def test_calls_correct_endpoint_for_base_id(self, mock_get, mock_sleep):
        mock_get.return_value = _mock_response({"tables": []})

        syncer = AirtableToPostgres()
        syncer.get_base_schema("appBASE123")

        mock_get.assert_called_once_with(
            "https://api.airtable.com/v0/meta/bases/appBASE123/tables",
            headers={"Authorization": "Bearer test-token"},
        )

    @patch("airtable_to_postgres.time.sleep")
    @patch("airtable_to_postgres.requests.get")
    def test_raises_when_request_fails(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("404 Not Found")
        mock_get.return_value = mock_resp

        syncer = AirtableToPostgres()
        try:
            syncer.get_base_schema("appMISSING")
            assert False, "expected an exception to propagate"
        except Exception as exc:
            assert "404" in str(exc)


class TestGetWorkspaceBases:
    @patch("airtable_to_postgres.time.sleep")
    @patch("airtable_to_postgres.requests.get")
    def test_returns_parsed_bases_list(self, mock_get, mock_sleep):
        payload = {
            "bases": [
                {"id": "appONE111", "name": "CRM"},
                {"id": "appTWO222", "name": "Inventory"},
            ]
        }
        mock_get.return_value = _mock_response(payload)

        syncer = AirtableToPostgres()
        bases = syncer.get_workspace_bases("wspABC123")

        assert bases == payload["bases"]
        assert bases[1]["name"] == "Inventory"
