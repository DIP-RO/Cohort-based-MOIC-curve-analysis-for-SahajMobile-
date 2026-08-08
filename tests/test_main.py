"""End-to-end tests for the pipeline entry point."""

import pandas as pd
import pytest

EXPECTED_OUTPUTS = [
    "cleaned_installments.csv",
    "excluded_rows.csv",
    "moic_table.csv",
    "cohort_summary.csv",
    "executive_insights.csv",
    "portfolio_summary.csv",
    "cumulative_moic_matrix.csv",
    "payment_moic_matrix.csv",
    "moic_curve.png",
    "net_moic_curve.png",
    "moic_dashboard.png",
]


@pytest.fixture()
def run_main(module, tmp_path, csv_path, raw_rows, monkeypatch):
    def _run(rows=None):
        out_dir = tmp_path / "outputs"
        monkeypatch.setattr(
            module.sys,
            "argv",
            ["prog", str(csv_path(rows if rows is not None else raw_rows)), str(out_dir)],
        )
        return module.main(), out_dir

    return _run


def test_main_writes_every_deliverable(run_main):
    _, out_dir = run_main()

    assert sorted(p.name for p in out_dir.iterdir()) == sorted(EXPECTED_OUTPUTS)


def test_main_returns_the_pipeline_frames(run_main):
    (cleaned, excluded, moic_df, summary, cum_matrix, pay_matrix), _ = run_main()

    assert len(cleaned) == 4
    assert excluded.empty
    assert sorted(summary["Cohort"]) == ["2024-01", "2024-02"]
    assert list(cum_matrix.columns)[0] == "Cohort"
    assert len(pay_matrix) == len(cum_matrix) == 2
    assert set(moic_df["Cohort"]) == {"2024-01", "2024-02"}


def test_written_moic_table_matches_returned_frame(run_main):
    (_, _, moic_df, _, _, _), out_dir = run_main()

    on_disk = pd.read_csv(out_dir / "moic_table.csv")

    assert on_disk["Cumulative_MOIC"].tolist() == pytest.approx(
        moic_df["Cumulative_MOIC"].tolist()
    )


def test_moic_values_for_the_sample_dataset(run_main):
    """Asset 1 advances 1,000 and repays 1,200 across MOB 1 and MOB 3."""
    (_, _, moic_df, _, _, _), _ = run_main()
    first = moic_df[moic_df["Cohort"] == "2024-01"]

    assert first["Months_on_Book"].tolist() == [1, 2, 3]
    assert first["Period_Collections"].tolist() == pytest.approx([600.0, 0.0, 600.0])
    assert first["Cumulative_MOIC"].tolist() == pytest.approx([0.6, 0.6, 1.2])
    assert first["Net_MOIC"].tolist() == pytest.approx([-0.4, -0.4, 0.2])


def test_main_creates_a_missing_output_directory(run_main):
    _, out_dir = run_main()

    assert out_dir.is_dir()


def test_main_reports_progress_sections(run_main, capsys):
    run_main()

    out = capsys.readouterr().out
    for marker in (
        "[1] Loading & Cleaning",
        "[2] Computing MOIC",
        "[3] Building Summary Tables",
        "COHORT SUMMARY TABLE",
        "PORTFOLIO SUMMARY",
        "[Done]",
    ):
        assert marker in out
