"""Tests for the XML builders and holdings-to-RTAC field mapping."""

from lxml import etree

from application import (
    ITEM_FIELDS,
    append_item,
    empty_item_information,
    holding_values,
)


def test_append_item_emits_all_fields_in_order():
    root = etree.Element("Item_Information")
    append_item(root, {"Item_no": "1", "Status": "Available"})
    item = root.find("Item")
    assert [child.tag for child in item] == ITEM_FIELDS
    assert item.findtext("Item_no") == "1"
    assert item.findtext("Status") == "Available"


def test_append_item_missing_and_none_become_empty_string():
    root = etree.Element("Item_Information")
    append_item(root, {"Status": None})  # everything else missing
    item = root.find("Item")
    # None -> "", missing key -> ""
    assert item.findtext("Status") == ""
    assert item.findtext("Call_No") == ""


def test_append_item_stringifies_non_string_values():
    root = etree.Element("Item_Information")
    append_item(root, {"Item_no": 1})
    assert root.find("Item").findtext("Item_no") == "1"


def test_append_item_returns_the_created_element():
    root = etree.Element("Item_Information")
    item = append_item(root, {})
    assert item.tag == "Item"
    assert item is root.find("Item")


def test_empty_item_information_has_single_unknown_placeholder():
    root = empty_item_information()
    assert root.tag == "Item_Information"
    items = root.findall("Item")
    assert len(items) == 1
    assert items[0].findtext("Status") == "Okänd"
    # All other fields are present but empty.
    assert items[0].findtext("Call_No") == ""


def test_empty_item_information_is_serialisable():
    xml = etree.tostring(empty_item_information(), encoding="unicode")
    assert "<Item_Information>" in xml
    assert "Okänd" in xml


def test_holding_values_maps_folio_fields():
    values = holding_values(
        {
            "id": "item-1",
            "location": "Main",
            "callNumber": "QA76",
            "status": "Available",
            "dueDate": "",
        }
    )
    assert values["UniqueItemId"] == "item-1"
    assert values["Location"] == "Main"
    assert values["Call_No"] == "QA76"
    assert values["Status"] == "Available"
    assert values["Item_no"] == "1"


def test_holding_values_truncates_due_date_to_iso_day():
    values = holding_values({"dueDate": "2024-05-01T12:34:56.000+00:00"})
    assert values["Status_Date"] == "2024-05-01"


def test_holding_values_handles_missing_fields():
    values = holding_values({})
    assert values["UniqueItemId"] == ""
    assert values["Status"] == ""
    assert values["Status_Date"] == ""  # ""[:10] == ""
    assert values["Loan_Policy"] == ""  # no permanentLoanType (mod-rtac)


def test_loan_policy_from_permanent_loan_type_string():
    values = holding_values({"permanentLoanType": "Can circulate"})
    assert values["Loan_Policy"] == "Can circulate"


def test_loan_policy_from_permanent_loan_type_object():
    values = holding_values({"permanentLoanType": {"id": "x", "name": "Course reserve"}})
    assert values["Loan_Policy"] == "Course reserve"


def test_loan_policy_empty_when_absent_or_nameless():
    assert holding_values({"permanentLoanType": None})["Loan_Policy"] == ""
    assert holding_values({"permanentLoanType": {}})["Loan_Policy"] == ""
    assert holding_values({"permanentLoanType": ""})["Loan_Policy"] == ""
