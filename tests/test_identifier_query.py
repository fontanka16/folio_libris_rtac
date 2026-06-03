"""Tests for CQL query building and the identifier-injection guard."""

import pytest

from application import _type_id_list, _VALID_IDENTIFIER, build_identifier_query


# Canonical UUIDs used as configured identifier-type ids.
T1 = "11111111-1111-1111-1111-111111111111"
T2 = "22222222-2222-2222-2222-222222222222"
T3 = "33333333-3333-3333-3333-333333333333"


# --- _type_id_list ----------------------------------------------------------


@pytest.mark.parametrize(
    "configured, expected",
    [
        (None, []),
        ("", []),
        ([], []),
        (T1, [T1]),                              # single UUID string
        ("{},{}".format(T1, T2), [T1, T2]),      # comma-separated string
        ([T1, T2], [T1, T2]),                    # list
        (" {} , {} ,, {} ".format(T1, T2, T3), [T1, T2, T3]),  # trims, drops empties
        ([T1, "", "  ", T2], [T1, T2]),          # empty entries don't count
    ],
)
def test_type_id_list_normalisation(configured, expected):
    assert _type_id_list(configured) == expected


def test_type_id_list_drops_non_uuid_with_warning(caplog):
    result = _type_id_list([T1, "not-a-uuid", "12345"], name="Bib_ID")
    assert result == [T1]
    assert "Ignoring invalid identifier-type UUID for Bib_ID" in caplog.text
    assert "not-a-uuid" in caplog.text


def test_type_id_list_empty_values_do_not_warn(caplog):
    # Empty / whitespace entries simply do not count -- no warning.
    assert _type_id_list(["", "   ", None], name="ISBN") == []
    assert "invalid" not in caplog.text.lower()


@pytest.mark.parametrize(
    "bad",
    [
        "1234",
        "not-a-uuid",
        "11111111111111111111111111111111",         # no hyphens
        "11111111-1111-1111-1111-11111111111",       # too short last group
        '11111111-1111-1111-1111-111111111111"',     # trailing quote (injection)
        "zzzzzzzz-1111-1111-1111-111111111111",       # non-hex
    ],
)
def test_type_id_list_rejects_malformed_uuids(bad):
    assert _type_id_list([bad], name="Bib_ID") == []


# --- build_identifier_query -------------------------------------------------


def test_single_identifier_one_uuid():
    query = build_identifier_query({"Bib_ID": "123"}, {"Bib_ID": [T1]})
    assert query == '?query=(identifiers=/@value/@identifierTypeId="{}" "123")'.format(T1)


def test_single_identifier_multiple_uuids_are_or_joined():
    query = build_identifier_query({"Bib_ID": "123"}, {"Bib_ID": [T1, T2]})
    assert query == (
        '?query=(identifiers=/@value/@identifierTypeId="{}" "123"'
        ' or identifiers=/@value/@identifierTypeId="{}" "123")'.format(T1, T2)
    )


def test_multiple_identifiers_combined():
    query = build_identifier_query(
        {"Bib_ID": "123", "ISBN": "978"},
        {"Bib_ID": [T1], "ISBN": [T2]},
    )
    assert '"{}" "123"'.format(T1) in query
    assert '"{}" "978"'.format(T2) in query
    assert " or " in query


def test_value_without_configured_uuid_is_skipped():
    # Value is set but no UUID configured for it -> no clause -> None.
    assert build_identifier_query({"ONR": "x"}, {"ONR": []}) is None


def test_value_with_only_invalid_uuid_yields_none():
    # The configured type id is junk, so the identifier contributes nothing.
    assert build_identifier_query({"Bib_ID": "123"}, {"Bib_ID": ["nope"]}) is None


def test_empty_values_yield_none():
    assert build_identifier_query({"Bib_ID": None, "ISSN": ""}, {"Bib_ID": [T1]}) is None


def test_no_identifiers_yield_none():
    assert build_identifier_query({}, {}) is None


def test_set_value_with_uuid_wins_over_unconfigured_one():
    query = build_identifier_query(
        {"Bib_ID": "123", "ONR": "456"},
        {"Bib_ID": [T1], "ONR": []},
    )
    assert query == '?query=(identifiers=/@value/@identifierTypeId="{}" "123")'.format(T1)


# --- identifier-value injection guard ---------------------------------------


@pytest.mark.parametrize(
    "evil",
    [
        '123" or 1==1',     # tries to break out of the quoted term
        'a"b',
        "a'b",
        "a*b",              # CQL wildcard
        "a(b)c",
        "a=b",
        "a\nb",
        "123\n",            # trailing newline must not slip past the \Z anchor
        "123\r",            # trailing carriage return likewise
        "x" * 129,          # exceeds the 128-char limit
        "",                 # empty never matches
    ],
)
def test_invalid_identifier_values_are_rejected(evil):
    assert not _VALID_IDENTIFIER.match(evil)


@pytest.mark.parametrize(
    "ok",
    [
        "123",
        "abc-DEF_0",
        "urn:nbn:se:libris-12345",
        "98.123/45",
        "x" * 128,          # exactly at the limit
    ],
)
def test_valid_identifier_values_are_accepted(ok):
    assert _VALID_IDENTIFIER.match(ok)


def test_injection_value_is_dropped_from_query(caplog):
    query = build_identifier_query({"Bib_ID": '123" or 1==1'}, {"Bib_ID": [T1]})
    # The only identifier was malicious, so nothing is searchable.
    assert query is None
    assert "Ignoring invalid Bib_ID identifier" in caplog.text


def test_injection_value_does_not_poison_a_valid_one():
    query = build_identifier_query(
        {"Bib_ID": "123", "ISBN": 'evil"'},
        {"Bib_ID": [T1], "ISBN": [T2]},
    )
    assert query == '?query=(identifiers=/@value/@identifierTypeId="{}" "123")'.format(T1)
    assert "evil" not in query
