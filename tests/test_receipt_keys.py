"""A receipt filename can contain a comma (it is minted from the expense item), so the
comma-separated ``files`` column is split only where the next key starts."""

from blueprints.report.services.receipt_keys import split_receipt_keys
from blueprints.report.services.shared import normalize_expense_files


def test_a_comma_inside_a_filename_is_not_a_separator():
    key = "expenses/a0505325-551f-4fa3-ae71-28856ee2516e/06_SEP_2026_STAFF_WELFARE_-_MEAL,_TRANSPORT_ETC_547.jpg"
    assert split_receipt_keys(key) == [key]
    assert [f["s3_key"] for f in normalize_expense_files(key)] == [key]
    assert normalize_expense_files(key)[0]["display_name"] == "06_SEP_2026_STAFF_WELFARE_-_MEAL,_TRANSPORT_ETC_547.jpg"


def test_keys_are_split_where_the_next_key_starts():
    value = "expenses/r/a.jpg,expenses/r/b,_c.jpg, attachments/x/y/z.jpeg,uploads/q.pdf,https://cdn/e.png"
    assert split_receipt_keys(value) == [
        "expenses/r/a.jpg", "expenses/r/b,_c.jpg", "attachments/x/y/z.jpeg", "uploads/q.pdf", "https://cdn/e.png",
    ]
    assert split_receipt_keys("") == [] and split_receipt_keys(None) == []


def test_a_new_receipt_name_is_letters_digits_and_underscores_only():
    from blueprints.report.services.receipt_keys import safe_extension, safe_stem

    assert safe_stem("Staff Welfare - Meal, Transport etc") == "STAFF_WELFARE_MEAL_TRANSPORT_ETC"
    assert safe_stem("Tea & coffee (staff)!") == "TEA_AND_COFFEE_STAFF"
    assert safe_stem("a/b\c:d*e?f\"g<h>i|j") == "A_B_C_D_E_F_G_H_I_J"
    assert safe_stem("  café  ") == "CAF"  # non-ASCII is not a stored-name character
    assert safe_stem("x" * 200).__len__() == 80 and safe_stem("") == "" and safe_stem(None) == ""
    assert safe_extension("receipt.JPG") == "jpg" and safe_extension("scan.pdf") == "pdf"
    assert safe_extension("weird.exe") == "jpg" and safe_extension("noext") == "jpg"
