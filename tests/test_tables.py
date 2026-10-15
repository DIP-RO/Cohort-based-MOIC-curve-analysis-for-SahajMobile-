"""Unit tests for the cohort summary, wide matrices and executive insights."""

import pandas as pd
import pytest


@pytest.fixture()
def tables_input(module):
    """A two-cohort MOIC table: 2024-01 reaches 1.3x, 2024-02 stays below 1.0x."""
    moic_df = pd.DataFrame(
        [
            ("2024-01", 1, 500.0, 1000.0),
            ("2024-01", 2, 500.0, 1000.0),
            ("2024-01", 3, 300.0, 1000.0),
            ("2024-02", 0, 400.0, 2000.0),
            ("2024-02", 1, 0.0, 2000.0),
            ("2024-02", 2, 600.0, 2000.0),
        ],
        columns=["Cohort", "Months_on_Book", "Period_Collections", "Cohort_Total_Advance"],
    )
    moic_df["Payment_MOIC"] = moic_df["Period_Collections"] / moic_df["Cohort_Total_Advance"]
    moic_df["Cumulative_Collections"] = moic_df.groupby("Cohort")["Period_Collections"].cumsum()
    moic_df["Cumulative_MOIC"] = (
        moic_df["Cumulative_Collections"] / moic_df["Cohort_Total_Advance"]
    )
    moic_df["Net_MOIC"] = moic_df["Cumulative_MOIC"] - 1.0

    cohort_meta = pd.DataFrame(
        [("2024-01", 2, 1000.0), ("2024-02", 1, 2000.0)],
        columns=["Cohort", "Asset_Count", "Cohort_Total_Advance"],
    )
    return moic_df, cohort_meta


def test_summary_columns_and_order(module, tables_input):
    summary, _, _ = module.build_tables(*tables_input)

    assert list(summary.columns) == [
        "Cohort",
        "Asset_Count",
        "Cohort_Total_Advance",
        "Total_Collected",
        "Max_Months_on_Book",
        "Max_Cumulative_MOIC",
        "Max_Net_MOIC",
        "Avg_Payment_MOIC",
    ]
    assert summary["Cohort"].tolist() == ["2024-01", "2024-02"]


def test_summary_kpis(module, tables_input):
    summary, _, _ = module.build_tables(*tables_input)
    first = summary.set_index("Cohort").loc["2024-01"]

    assert first["Total_Collected"] == pytest.approx(1300.0)
    assert first["Max_Months_on_Book"] == 3
    assert first["Max_Cumulative_MOIC"] == pytest.approx(1.3)
    assert first["Max_Net_MOIC"] == pytest.approx(0.3)
    assert first["Avg_Payment_MOIC"] == pytest.approx((0.5 + 0.5 + 0.3) / 3)


def test_summary_keeps_cohorts_absent_from_the_moic_table(module, tables_input):
    moic_df, cohort_meta = tables_input
    cohort_meta = pd.concat(
        [cohort_meta, pd.DataFrame([("2024-03", 4, 500.0)], columns=cohort_meta.columns)],
        ignore_index=True,
    )

    summary, _, _ = module.build_tables(moic_df, cohort_meta)
    unpaid = summary.set_index("Cohort").loc["2024-03"]

    assert unpaid["Asset_Count"] == 4
    assert pd.isna(unpaid["Total_Collected"])


def test_matrices_are_wide_with_mob_columns(module, tables_input):
    _, cum_matrix, pay_matrix = module.build_tables(*tables_input)

    assert list(cum_matrix.columns) == ["Cohort", "MOB_0", "MOB_1", "MOB_2", "MOB_3"]
    assert list(pay_matrix.columns) == list(cum_matrix.columns)
    assert cum_matrix.columns.name is None

    row = cum_matrix.set_index("Cohort").loc["2024-01"]
    assert pd.isna(row["MOB_0"])
    assert row["MOB_3"] == pytest.approx(1.3)
    assert pay_matrix.set_index("Cohort").loc["2024-02", "MOB_1"] == pytest.approx(0.0)


def test_insights_ranks_cohorts_by_latest_cumulative_moic(module, tables_input):
    summary, _, _ = module.build_tables(*tables_input)
    insights, _ = module.build_executive_insights(tables_input[0], summary)

    assert insights["Cohort"].tolist() == ["2024-01", "2024-02"]
    assert insights.set_index("Cohort").loc["2024-01", "Latest_MOB"] == 3
    assert insights.set_index("Cohort").loc["2024-02", "Latest_Cumulative_MOIC"] == pytest.approx(0.5)


def test_insights_threshold_crossings(module, tables_input):
    summary, _, _ = module.build_tables(*tables_input)
    insights, _ = module.build_executive_insights(tables_input[0], summary)
    indexed = insights.set_index("Cohort")

    assert indexed.loc["2024-01", "Months_to_Breakeven"] == 2
    assert indexed.loc["2024-01", "Months_to_Target_1_3x"] == 3
    # Never crossed — nullable integer keeps the column integer-typed.
    assert pd.isna(indexed.loc["2024-02", "Months_to_Breakeven"])
    assert str(indexed["Months_to_Breakeven"].dtype) == "Int64"


@pytest.mark.parametrize(
    "latest_moic, expected",
    [(1.4, "Beyond target"), (1.3, "Beyond target"), (1.0, "Recovered"), (0.9, "Below breakeven")],
)
def test_recovery_status_thresholds(module, tables_input, latest_moic, expected):
    moic_df, cohort_meta = tables_input
    single = moic_df[moic_df["Cohort"] == "2024-01"].copy()
    single["Cumulative_MOIC"] = [0.1, 0.2, latest_moic]
    summary, _, _ = module.build_tables(single, cohort_meta[cohort_meta["Cohort"] == "2024-01"])

    insights, _ = module.build_executive_insights(single, summary)

    assert insights["Recovery_Status"].tolist() == [expected]


def test_seasoned_flag_needs_twelve_months_on_book(module, tables_input):
    moic_df, cohort_meta = tables_input
    seasoned = moic_df[moic_df["Cohort"] == "2024-01"].copy()
    seasoned["Months_on_Book"] = [10, 11, 12]
    summary, _, _ = module.build_tables(seasoned, cohort_meta[cohort_meta["Cohort"] == "2024-01"])

    insights, _ = module.build_executive_insights(seasoned, summary)

    assert insights["Seasoned_12M"].tolist() == [True]


def test_share_percentages_sum_to_one_hundred(module, tables_input):
    summary, _, _ = module.build_tables(*tables_input)
    insights, _ = module.build_executive_insights(tables_input[0], summary)

    assert insights["Collection_Share_Pct"].sum() == pytest.approx(100.0)
    assert insights["Advance_Share_Pct"].sum() == pytest.approx(100.0)


def test_portfolio_summary_metrics(module, tables_input):
    summary, _, _ = module.build_tables(*tables_input)
    _, portfolio = module.build_executive_insights(tables_input[0], summary)
    values = dict(zip(portfolio["Metric"], portfolio["Value"]))

    # 2,300 collected against 3,000 advanced.
    assert values["Portfolio Recovery Rate"] == pytest.approx(round(2300 / 3000, 4))
    assert values["Cohorts Above 1.0x"] == 1
    assert values["Cohorts Above 1.3x"] == 1
    assert values["Seasoned Cohorts (12M+)"] == 0
    assert values["Recovered Cohort Share"] == pytest.approx(round(1300 / 2300 * 100, 2))
    assert list(portfolio.columns) == ["Metric", "Value", "Unit"]


def test_insights_columns_are_stable(module, tables_input):
    summary, _, _ = module.build_tables(*tables_input)
    insights, _ = module.build_executive_insights(tables_input[0], summary)

    assert list(insights.columns) == [
        "Cohort",
        "Recovery_Status",
        "Seasoned_12M",
        "Latest_MOB",
        "Latest_Cumulative_MOIC",
        "Months_to_Breakeven",
        "Months_to_Target_1_3x",
        "Collection_Share_Pct",
        "Advance_Share_Pct",
        "Max_Cumulative_MOIC",
    ]
