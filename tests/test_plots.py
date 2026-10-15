"""Unit tests for the chart renderers."""

import matplotlib.pyplot as plt
import pytest


@pytest.fixture()
def rendered(module, moic_frame, tmp_path):
    """Render every chart once and expose the figures captured before closing."""
    moic_df, cohort_meta = moic_frame
    summary, _, _ = module.build_tables(moic_df, cohort_meta)
    return moic_df, summary, tmp_path


def test_moic_curve_is_written_and_figure_closed(module, rendered):
    moic_df, _, tmp_path = rendered
    out = tmp_path / "moic_curve.png"

    module.plot_moic_curves(moic_df, str(out))

    assert out.stat().st_size > 0
    assert plt.get_fignums() == []


def test_net_moic_curve_is_written(module, rendered):
    moic_df, _, tmp_path = rendered
    out = tmp_path / "net_moic_curve.png"

    module.plot_net_moic_curves(moic_df, str(out))

    assert out.stat().st_size > 0
    assert plt.get_fignums() == []


def test_dashboard_is_written(module, rendered):
    moic_df, summary, tmp_path = rendered
    out = tmp_path / "moic_dashboard.png"

    module.plot_executive_dashboard(moic_df, summary, str(out))

    assert out.stat().st_size > 0
    assert plt.get_fignums() == []


def test_curve_draws_one_line_per_cohort(module, rendered, monkeypatch):
    moic_df, _, tmp_path = rendered
    captured = {}
    original = plt.subplots

    def _spy(*args, **kwargs):
        fig, ax = original(*args, **kwargs)
        captured["ax"] = ax
        return fig, ax

    monkeypatch.setattr(module.plt, "subplots", _spy)
    module.plot_moic_curves(moic_df, str(tmp_path / "curve.png"))

    labels = [line.get_label() for line in captured["ax"].get_lines()]
    for cohort in moic_df["Cohort"].unique():
        assert cohort in labels


def test_curve_omits_target_line_when_far_above_the_data(module, rendered, monkeypatch):
    """The 1.30x reference line only appears when it is near the plotted range."""
    moic_df, _, tmp_path = rendered
    low = moic_df.copy()
    low["Cumulative_MOIC"] = 0.1
    captured = {}
    original = plt.subplots

    def _spy(*args, **kwargs):
        fig, ax = original(*args, **kwargs)
        captured["ax"] = ax
        return fig, ax

    monkeypatch.setattr(module.plt, "subplots", _spy)
    module.plot_moic_curves(low, str(tmp_path / "low.png"))

    annotations = [text.get_text() for text in captured["ax"].texts]
    assert annotations == []


def test_charts_handle_a_single_cohort(module, moic_frame, tmp_path):
    moic_df, cohort_meta = moic_frame
    one = moic_df[moic_df["Cohort"] == moic_df["Cohort"].iloc[0]]
    summary, _, _ = module.build_tables(one, cohort_meta[cohort_meta["Cohort"] == one["Cohort"].iloc[0]])

    module.plot_moic_curves(one, str(tmp_path / "one_curve.png"))
    module.plot_net_moic_curves(one, str(tmp_path / "one_net.png"))
    module.plot_executive_dashboard(one, summary, str(tmp_path / "one_dash.png"))

    assert (tmp_path / "one_curve.png").exists()
    assert (tmp_path / "one_net.png").exists()
    assert (tmp_path / "one_dash.png").exists()


def test_plot_logs_output_path(module, rendered, capsys):
    moic_df, _, tmp_path = rendered
    out = tmp_path / "logged.png"

    module.plot_moic_curves(moic_df, str(out))

    assert str(out) in capsys.readouterr().out
