"""Unit tests for loading, standardising and QA-filtering the raw dataset."""

import pandas as pd
import pytest


def _row(**overrides):
    row = {
        "Asset ID": 1,
        "Origination Date": "1/31/2024",
        " Total Advance ": " 1,000 ",
        " Total EMI ": " 1,200 ",
        "Payment Date": "2/7/2024",
        " Payment Amount ": " 600 ",
    }
    row.update(overrides)
    return row


def test_columns_are_standardised_and_types_parsed(module, csv_path):
    cleaned, _ = module.load_and_clean(str(csv_path([_row()])))

    assert list(cleaned.columns) == [
        "Asset_ID",
        "Origination_Date",
        "Total_Advance",
        "Total_EMI",
        "Payment_Date",
        "Payment_Amount",
        "Months_on_Book",
        "Cohort",
    ]
    assert cleaned["Total_Advance"].iloc[0] == 1000.0
    assert cleaned["Total_EMI"].iloc[0] == 1200.0
    assert cleaned["Payment_Amount"].iloc[0] == 600.0
    assert cleaned["Origination_Date"].iloc[0] == pd.Timestamp("2024-01-31")
    assert cleaned["Payment_Date"].iloc[0] == pd.Timestamp("2024-02-07")


def test_exact_duplicates_are_dropped(module, csv_path):
    cleaned, excluded = module.load_and_clean(str(csv_path([_row(), _row()])))

    assert len(cleaned) == 1
    assert excluded.empty


def test_near_duplicates_are_kept(module, csv_path):
    rows = [_row(), _row(**{"Payment Date": "3/7/2024"})]
    cleaned, _ = module.load_and_clean(str(csv_path(rows)))

    assert len(cleaned) == 2


def test_months_on_book_uses_calendar_month_distance(module, csv_path):
    rows = [
        _row(**{"Payment Date": "2/1/2024"}),   # 1 day later, next month  -> 1
        _row(**{"Payment Date": "4/30/2024"}),  # three calendar months    -> 3
        _row(**{"Payment Date": "1/1/2025"}),   # crosses the year         -> 12
    ]
    cleaned, _ = module.load_and_clean(str(csv_path(rows)))

    assert sorted(cleaned["Months_on_Book"]) == [1, 3, 12]
    assert cleaned["Months_on_Book"].dtype.kind == "i"


def test_same_month_payment_is_mob_zero(module, csv_path):
    rows = [_row(**{"Origination Date": "1/1/2024", "Payment Date": "1/20/2024"})]
    cleaned, _ = module.load_and_clean(str(csv_path(rows)))

    assert cleaned["Months_on_Book"].tolist() == [0]


def test_cohort_is_origination_month(module, csv_path):
    rows = [
        _row(**{"Origination Date": "1/31/2024", "Payment Date": "2/7/2024"}),
        _row(**{"Asset ID": 2, "Origination Date": "12/5/2023", "Payment Date": "1/9/2024"}),
    ]
    cleaned, _ = module.load_and_clean(str(csv_path(rows)))

    assert sorted(cleaned["Cohort"]) == ["2023-12", "2024-01"]


def test_missing_payment_amount_becomes_zero(module, csv_path):
    rows = [_row(**{" Payment Amount ": "n/a"})]
    cleaned, _ = module.load_and_clean(str(csv_path(rows)))

    assert cleaned["Payment_Amount"].tolist() == [0.0]


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"Origination Date": "not-a-date"}, "Unparseable Origination_Date"),
        ({"Payment Date": "not-a-date"}, "Unparseable Payment_Date"),
        (
            {"Payment Date": "1/1/1970"},
            "Sentinel / Epoch Payment_Date (1970-01-01)",
        ),
        (
            {"Origination Date": "3/1/2024", "Payment Date": "2/1/2024"},
            "Payment_Date before Origination_Date",
        ),
        (
            {"Payment Date": "3/1/2027"},
            "Months on Book > 24 — likely data entry error",
        ),
        ({" Total Advance ": " - "}, "Missing or non-positive Total_Advance"),
        ({" Total Advance ": "n/a"}, "Missing or non-positive Total_Advance"),
    ],
)
def test_each_anomaly_is_excluded_with_its_reason(module, csv_path, overrides, reason):
    cleaned, excluded = module.load_and_clean(str(csv_path([_row(**overrides)])))

    assert cleaned.empty
    assert excluded["Exclusion_Reason"].tolist() == [reason]


def test_mob_boundary_of_24_months_is_kept(module, csv_path):
    rows = [_row(**{"Origination Date": "1/31/2024", "Payment Date": "1/5/2026"})]
    cleaned, excluded = module.load_and_clean(str(csv_path(rows)))

    assert cleaned["Months_on_Book"].tolist() == [24]
    assert excluded.empty


def test_max_mob_threshold_is_configurable(module, csv_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_MOB", 1)
    rows = [_row(**{"Payment Date": "5/7/2024"})]

    cleaned, excluded = module.load_and_clean(str(csv_path(rows)))

    assert cleaned.empty
    assert excluded["Exclusion_Reason"].tolist() == [
        "Months on Book > 1 — likely data entry error"
    ]


def test_each_excluded_row_gets_exactly_one_reason(module, csv_path):
    """The epoch sentinel also predates origination; the first match wins."""
    rows = [_row(**{"Origination Date": "1/6/2026", "Payment Date": "1/1/1970"})]

    _, excluded = module.load_and_clean(str(csv_path(rows)))

    assert excluded["Exclusion_Reason"].tolist() == [
        "Sentinel / Epoch Payment_Date (1970-01-01)"
    ]


def test_valid_and_invalid_rows_are_partitioned(module, csv_path):
    rows = [
        _row(),
        _row(**{"Asset ID": 2, "Payment Date": "1/1/1970"}),
        _row(**{"Asset ID": 3, " Total Advance ": " - "}),
    ]
    cleaned, excluded = module.load_and_clean(str(csv_path(rows)))

    assert cleaned["Asset_ID"].tolist() == [1]
    assert sorted(excluded["Asset_ID"]) == [2, 3]
    assert "Months_on_Book" not in excluded.columns


def test_all_rows_excluded_yields_empty_cleaned_frame(module, csv_path):
    rows = [_row(**{"Payment Date": "bad"}), _row(**{"Asset ID": 2, "Payment Date": "bad"})]

    cleaned, excluded = module.load_and_clean(str(csv_path(rows)))

    assert cleaned.empty
    assert len(excluded) == 2


def test_diagnostics_report_row_counts(module, csv_path, capsys):
    rows = [_row(), _row(), _row(**{"Asset ID": 2, "Payment Date": "1/1/1970"})]

    module.load_and_clean(str(csv_path(rows)))

    out = capsys.readouterr().out
    assert "Raw rows            :       3" in out
    assert "Exact duplicates    :       1" in out
    assert "Anomalous/excluded  :       1" in out
    assert "Exclusion breakdown:" in out
