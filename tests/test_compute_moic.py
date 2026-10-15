"""Unit tests for the cohort × months-on-book MOIC aggregation."""

import pandas as pd
import pytest


def _cleaned(rows):
    """Build an analysis-ready frame in the shape ``load_and_clean`` returns."""
    frame = pd.DataFrame(
        rows,
        columns=["Asset_ID", "Cohort", "Total_Advance", "Months_on_Book", "Payment_Amount"],
    )
    frame["Origination_Date"] = pd.to_datetime(frame["Cohort"] + "-01")
    return frame


def test_payment_and_cumulative_moic_use_cohort_advance(module):
    cleaned = _cleaned([
        (1, "2024-01", 1000.0, 1, 600.0),
        (1, "2024-01", 1000.0, 2, 700.0),
    ])

    moic_df, _ = module.compute_moic(cleaned)

    assert moic_df["Payment_MOIC"].tolist() == pytest.approx([0.6, 0.7])
    assert moic_df["Cumulative_Collections"].tolist() == pytest.approx([600.0, 1300.0])
    assert moic_df["Cumulative_MOIC"].tolist() == pytest.approx([0.6, 1.3])


def test_net_moic_is_cumulative_moic_minus_one(module, moic_frame):
    moic_df, _ = moic_frame

    assert moic_df["Net_MOIC"].tolist() == pytest.approx(
        (moic_df["Cumulative_MOIC"] - 1.0).tolist()
    )


def test_advance_counted_once_per_asset(module):
    """The advance repeats on every instalment row but must be summed per asset."""
    cleaned = _cleaned([
        (1, "2024-01", 1000.0, 1, 100.0),
        (1, "2024-01", 1000.0, 2, 100.0),
        (2, "2024-01", 500.0, 1, 50.0),
        (2, "2024-01", 500.0, 2, 50.0),
    ])

    _, cohort_meta = module.compute_moic(cleaned)

    assert cohort_meta["Cohort_Total_Advance"].tolist() == [1500.0]
    assert cohort_meta["Asset_Count"].tolist() == [2]


def test_zero_payment_rows_do_not_extend_the_curve(module):
    """Scheduled-but-unpaid slots must not add trailing months to a cohort."""
    cleaned = _cleaned([
        (1, "2024-01", 1000.0, 1, 600.0),
        (1, "2024-01", 1000.0, 5, 0.0),
    ])

    moic_df, _ = module.compute_moic(cleaned)

    assert moic_df["Months_on_Book"].tolist() == [1]


def test_gap_months_are_filled_with_zero_collections(module):
    cleaned = _cleaned([
        (1, "2024-01", 1000.0, 1, 400.0),
        (1, "2024-01", 1000.0, 4, 300.0),
    ])

    moic_df, _ = module.compute_moic(cleaned)

    assert moic_df["Months_on_Book"].tolist() == [1, 2, 3, 4]
    assert moic_df["Period_Collections"].tolist() == pytest.approx([400.0, 0.0, 0.0, 300.0])
    # Cumulative curve stays flat across the gap instead of skipping months.
    assert moic_df["Cumulative_MOIC"].tolist() == pytest.approx([0.4, 0.4, 0.4, 0.7])


def test_gap_filling_does_not_backfill_before_first_collection(module):
    cleaned = _cleaned([(1, "2024-01", 1000.0, 3, 500.0)])

    moic_df, _ = module.compute_moic(cleaned)

    assert moic_df["Months_on_Book"].tolist() == [3]


def test_cumulative_totals_are_independent_per_cohort(module):
    cleaned = _cleaned([
        (1, "2024-01", 1000.0, 1, 400.0),
        (1, "2024-01", 1000.0, 2, 300.0),
        (2, "2024-02", 2000.0, 1, 500.0),
        (2, "2024-02", 2000.0, 2, 500.0),
    ])

    moic_df, _ = module.compute_moic(cleaned)
    by_cohort = moic_df.set_index(["Cohort", "Months_on_Book"])["Cumulative_Collections"]

    assert by_cohort[("2024-01", 2)] == pytest.approx(700.0)
    assert by_cohort[("2024-02", 2)] == pytest.approx(1000.0)


def test_payments_from_several_assets_are_pooled_per_period(module):
    cleaned = _cleaned([
        (1, "2024-01", 1000.0, 1, 400.0),
        (2, "2024-01", 1000.0, 1, 250.0),
    ])

    moic_df, _ = module.compute_moic(cleaned)

    assert moic_df["Period_Collections"].tolist() == pytest.approx([650.0])
    assert moic_df["Cumulative_MOIC"].tolist() == pytest.approx([0.325])


def test_output_is_sorted_by_cohort_then_month(module):
    cleaned = _cleaned([
        (2, "2024-02", 2000.0, 2, 500.0),
        (1, "2024-01", 1000.0, 3, 300.0),
        (1, "2024-01", 1000.0, 1, 400.0),
        (2, "2024-02", 2000.0, 1, 500.0),
    ])

    moic_df, _ = module.compute_moic(cleaned)

    assert moic_df[["Cohort", "Months_on_Book"]].values.tolist() == [
        ["2024-01", 1],
        ["2024-01", 2],
        ["2024-01", 3],
        ["2024-02", 1],
        ["2024-02", 2],
    ]


def test_cohort_meta_covers_cohorts_without_any_collection(module):
    """A cohort whose instalments are all unpaid still contributes its advance."""
    cleaned = _cleaned([
        (1, "2024-01", 1000.0, 1, 600.0),
        (2, "2024-02", 2000.0, 1, 0.0),
    ])

    moic_df, cohort_meta = module.compute_moic(cleaned)

    assert sorted(cohort_meta["Cohort"]) == ["2024-01", "2024-02"]
    assert moic_df["Cohort"].unique().tolist() == ["2024-01"]


def test_diagnostics_report_cohort_and_peak_metrics(module, capsys):
    cleaned = _cleaned([
        (1, "2024-01", 1000.0, 1, 600.0),
        (1, "2024-01", 1000.0, 2, 700.0),
    ])

    module.compute_moic(cleaned)

    out = capsys.readouterr().out
    assert "Cohorts in MOIC table : 1" in out
    assert "Max Months on Book    : 2" in out
    assert "1.3000×" in out
    assert "+0.3000×" in out
