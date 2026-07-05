"""
Unit tests for the pure, side-effect-free transformation helpers on
AirtableToPostgres: sanitize_name, map_airtable_type_to_postgres, and
convert_value_for_postgres.

These three methods contain no I/O (no HTTP, no database) and are the
core "business logic" of the mirror: they decide how Airtable names,
field types, and values get translated into PostgreSQL-safe equivalents.

AirtableToPostgres.__init__ requires AIRTABLE_TOKEN to be set, or it
raises ValueError. We set a dummy token before importing the module so
the class can be instantiated in CI without real Airtable credentials.
"""

import os

os.environ["AIRTABLE_TOKEN"] = "test-token"

import pytest

from airtable_to_postgres import AirtableToPostgres


@pytest.fixture(scope="module")
def syncer():
    """A single AirtableToPostgres instance shared across tests in this module.

    Construction only reads AIRTABLE_TOKEN from the environment; it does not
    open any network or database connection.
    """
    return AirtableToPostgres()


class TestSanitizeName:
    """sanitize_name: special chars -> underscores, collapse doubles, strip, lowercase."""

    def test_replaces_spaces_with_underscores(self, syncer):
        assert syncer.sanitize_name("Customer Name") == "customer_name"

    def test_replaces_special_characters(self, syncer):
        assert syncer.sanitize_name("Order #123!") == "order_123"

    def test_collapses_consecutive_underscores(self, syncer):
        assert syncer.sanitize_name("Foo   Bar") == "foo_bar"

    def test_collapses_many_consecutive_underscores(self, syncer):
        assert syncer.sanitize_name("Foo------Bar") == "foo_bar"

    def test_strips_leading_and_trailing_underscores(self, syncer):
        assert syncer.sanitize_name("__Weird Field__") == "weird_field"

    def test_strips_leading_and_trailing_special_chars(self, syncer):
        assert syncer.sanitize_name("!!!Status!!!") == "status"

    def test_lowercases_result(self, syncer):
        assert syncer.sanitize_name("CamelCaseField") == "camelcasefield"

    def test_preserves_alphanumeric_only_name(self, syncer):
        assert syncer.sanitize_name("email") == "email"

    def test_preserves_digits(self, syncer):
        assert syncer.sanitize_name("Q1_2024_Revenue") == "q1_2024_revenue"

    def test_handles_mixed_unicode_and_punctuation(self, syncer):
        # str.isalnum() considers accented letters alphanumeric, so they are
        # preserved; only the punctuation/whitespace is replaced.
        assert syncer.sanitize_name("Café / Résumé") == "café_résumé"

    def test_empty_string_after_sanitizing_stays_empty(self, syncer):
        assert syncer.sanitize_name("!!!") == ""

    def test_slashes_and_parens_become_single_underscore(self, syncer):
        assert syncer.sanitize_name("Revenue (USD)/Quarter") == "revenue_usd_quarter"


class TestMapAirtableTypeToPostgres:
    """map_airtable_type_to_postgres: known Airtable field types -> Postgres column types."""

    @pytest.mark.parametrize(
        "airtable_type,expected_pg_type",
        [
            ("singleLineText", "TEXT"),
            ("multilineText", "TEXT"),
            ("richText", "TEXT"),
            ("number", "NUMERIC"),
            ("checkbox", "BOOLEAN"),
            ("singleSelect", "TEXT"),
            ("multipleSelects", "JSONB"),
            ("date", "DATE"),
            ("dateTime", "TIMESTAMP WITH TIME ZONE"),
            ("email", "TEXT"),
            ("url", "TEXT"),
            ("phone", "TEXT"),
            ("currency", "NUMERIC"),
            ("percent", "NUMERIC"),
            ("autoNumber", "SERIAL"),
            ("rating", "INTEGER"),
            ("formula", "JSONB"),
            ("rollup", "JSONB"),
            ("lookup", "JSONB"),
            ("multipleRecordLinks", "JSONB"),
            ("singleRecordLink", "JSONB"),
            ("attachment", "JSONB"),
            ("barcode", "JSONB"),
            ("button", "JSONB"),
            ("createdTime", "TIMESTAMP WITH TIME ZONE"),
            ("lastModifiedTime", "TIMESTAMP WITH TIME ZONE"),
            ("createdBy", "JSONB"),
            ("lastModifiedBy", "JSONB"),
        ],
    )
    def test_known_type_mappings(self, syncer, airtable_type, expected_pg_type):
        assert syncer.map_airtable_type_to_postgres(airtable_type) == expected_pg_type

    def test_unknown_type_defaults_to_text(self, syncer):
        assert syncer.map_airtable_type_to_postgres("someBrandNewFieldType") == "TEXT"

    def test_empty_string_type_defaults_to_text(self, syncer):
        assert syncer.map_airtable_type_to_postgres("") == "TEXT"

    def test_type_lookup_is_case_sensitive(self, syncer):
        # Airtable types are camelCase; an incorrectly-cased type should not
        # accidentally match and should fall back to the TEXT default.
        assert syncer.map_airtable_type_to_postgres("SingleLineText") == "TEXT"


class TestConvertValueForPostgres:
    """convert_value_for_postgres: normalize Airtable field values for insertion."""

    def test_dict_is_json_encoded(self, syncer):
        result = syncer.convert_value_for_postgres({"id": "rec123", "name": "Acme"})
        assert result == '{"id": "rec123", "name": "Acme"}'
        assert isinstance(result, str)

    def test_list_is_json_encoded(self, syncer):
        result = syncer.convert_value_for_postgres(["Alpha", "Beta"])
        assert result == '["Alpha", "Beta"]'
        assert isinstance(result, str)

    def test_list_of_dicts_is_json_encoded(self, syncer):
        value = [{"id": "att1", "url": "https://example.com/a.png"}]
        result = syncer.convert_value_for_postgres(value)
        assert result == '[{"id": "att1", "url": "https://example.com/a.png"}]'

    def test_bool_true_passes_through_unchanged(self, syncer):
        result = syncer.convert_value_for_postgres(True)
        assert result is True

    def test_bool_false_passes_through_unchanged(self, syncer):
        result = syncer.convert_value_for_postgres(False)
        assert result is False

    def test_none_passes_through_as_none(self, syncer):
        assert syncer.convert_value_for_postgres(None) is None

    def test_int_passes_through_unchanged(self, syncer):
        result = syncer.convert_value_for_postgres(42)
        assert result == 42
        assert isinstance(result, int)

    def test_float_passes_through_unchanged(self, syncer):
        result = syncer.convert_value_for_postgres(3.14)
        assert result == 3.14
        assert isinstance(result, float)

    def test_string_falls_through_as_str(self, syncer):
        result = syncer.convert_value_for_postgres("hello")
        assert result == "hello"
        assert isinstance(result, str)

    def test_bool_is_checked_before_numeric_fallback(self, syncer):
        # bool is a subclass of int in Python; convert_value_for_postgres checks
        # isinstance(value, bool) before isinstance(value, (int, float)), so
        # True/False must stay Python booleans rather than becoming 1/0.
        result = syncer.convert_value_for_postgres(True)
        assert result is True
        assert result != 1 or isinstance(result, bool)
