#!/usr/bin/env python3
"""
sahajmobile_moic.py
====================
Cohort-based MOIC curve analysis for SahajMobile installment payment data.

Formula reference
-----------------
  Payment MOIC    = Period collections  ÷ Cohort total advance
  Cumulative MOIC = Running collections ÷ Cohort total advance

Outputs (all written to OUTPUT_DIR)
------------------------------------
  cleaned_installments.csv    – deduplicated, parsed, QA-filtered dataset
  excluded_rows.csv           – removed rows annotated with exclusion reason
  moic_table.csv              – long-form Period + Cumulative MOIC (cohort × MOB)
  cohort_summary.csv          – one-row-per-cohort KPI table
  cumulative_moic_matrix.csv  – wide pivot: cohort × MOB → Cumulative MOIC
  payment_moic_matrix.csv     – wide pivot: cohort × MOB → Payment MOIC
  moic_curve.png              – vintage MOIC curve chart
    moic_dashboard.png          – executive-style multi-panel cohort dashboard
"""

import os
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ─── Configuration ─────────────────────────────────────────────────────────────
# Resolution order for input/output paths: CLI args → env vars → defaults below.
# Usage:  python sahajmobile_moic.py [input.csv] [output_dir]
BASE_DIR   = Path(__file__).resolve().parent
INPUT_PATH = os.environ.get(
    "SAHAJMOBILE_INPUT", str(BASE_DIR / "Installment_shorter_sampled.csv")
)
OUTPUT_DIR = os.environ.get("SAHAJMOBILE_OUTPUT", str(BASE_DIR / "outputs"))

# Payments > MAX_MOB months after origination are flagged as anomalous.
# Chosen as 24 months (generous upper bound for a phone EMI loan).
MAX_MOB = 24


def resolve_paths() -> tuple[str, str]:
    """Resolve (input_csv, output_dir): CLI args → env vars → script defaults."""
    in_path  = sys.argv[1] if len(sys.argv) > 1 else INPUT_PATH
    out_path = sys.argv[2] if len(sys.argv) > 2 else OUTPUT_DIR

    if not os.path.exists(in_path):
        print(f"[Error] Input file not found: {in_path}")
        print(f"  Usage: python {Path(__file__).name} [input.csv] [output_dir]")
        sys.exit(1)

    os.makedirs(out_path, exist_ok=True)
    return in_path, out_path


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 · LOAD & CLEAN
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_money(series: pd.Series) -> pd.Series:
    """
    Convert messy currency strings to float.

    Examples
    --------
    ' 17,160 ' → 17160.0
    ' - '      →     0.0   (dash = scheduled but unpaid)
    ' 9,000 '  →  9000.0
    NaN        →     NaN
    """
    def _conv(v):
        if pd.isna(v):
            return np.nan
        s = str(v).strip().replace(",", "").replace(" ", "")
        # Strip all dash variants (unicode en-dash, em-dash, minus, hyphen)
        for ch in ("\u2014", "\u2013", "\u2212", "-"):
            s = s.replace(ch, "")
        if s in ("", "."):
            return 0.0
        try:
            return float(s)
        except ValueError:
            return np.nan

    return series.map(_conv)


def load_and_clean(filepath: str) -> tuple:
    """
    Load the raw CSV, standardise column names and data types, remove exact
    duplicates, and separate anomalous rows.

    Returns
    -------
    cleaned  : pd.DataFrame – analysis-ready rows with added derived columns
    excluded : pd.DataFrame – removed rows with Exclusion_Reason annotation
    """
    # ── Load ──────────────────────────────────────────────────────────────────
    raw = pd.read_csv(filepath)
    raw.columns = raw.columns.str.strip()
    raw = raw.rename(
        columns={
            "Asset ID":         "Asset_ID",
            "Origination Date": "Origination_Date",
            "Total Advance":    "Total_Advance",
            "Total EMI":        "Total_EMI",
            "Payment Date":     "Payment_Date",
            "Payment Amount":   "Payment_Amount",
        }
    )

    # ── Parse numeric columns ─────────────────────────────────────────────────
    raw["Total_Advance"]  = _parse_money(raw["Total_Advance"])
    raw["Total_EMI"]      = _parse_money(raw["Total_EMI"])
    raw["Payment_Amount"] = _parse_money(raw["Payment_Amount"])

    # ── Parse date columns ────────────────────────────────────────────────────
    raw["Origination_Date"] = pd.to_datetime(
        raw["Origination_Date"], errors="coerce", dayfirst=False
    )
    raw["Payment_Date"] = pd.to_datetime(
        raw["Payment_Date"], errors="coerce", dayfirst=False
    )

    # ── Step 1: Remove exact duplicate rows ───────────────────────────────────
    n_raw   = len(raw)
    raw     = raw.drop_duplicates()
    n_dupes = n_raw - len(raw)

    # ── Step 2: Build exclusion masks (first match wins per row) ──────────────
    EPOCH    = pd.Timestamp("1970-01-01")
    both     = raw["Payment_Date"].notna() & raw["Origination_Date"].notna()

    def _mob_series(df):
        """Calendar-month distance: Payment_Date - Origination_Date (in months)."""
        return (
            (df["Payment_Date"].dt.year  - df["Origination_Date"].dt.year)  * 12
            + (df["Payment_Date"].dt.month - df["Origination_Date"].dt.month)
        )

    masks = {
        "Unparseable Origination_Date":
            raw["Origination_Date"].isna(),

        "Unparseable Payment_Date":
            raw["Payment_Date"].isna(),

        "Sentinel / Epoch Payment_Date (1970-01-01)":
            raw["Payment_Date"] == EPOCH,

        "Payment_Date before Origination_Date":
            both & (raw["Payment_Date"] < raw["Origination_Date"]),

        f"Months on Book > {MAX_MOB} — likely data entry error":
            both & (_mob_series(raw) > MAX_MOB),

        "Missing or non-positive Total_Advance":
            raw["Total_Advance"].isna() | (raw["Total_Advance"] <= 0),
    }

    # First-match exclusion: each row gets at most one reason label
    excl_idx  = []
    excl_why  = []
    seen      = set()
    for reason, mask in masks.items():
        new_idx = [i for i in raw.index[mask] if i not in seen]
        excl_idx.extend(new_idx)
        excl_why.extend([reason] * len(new_idx))
        seen.update(new_idx)

    excluded = raw.loc[excl_idx].copy()
    excluded["Exclusion_Reason"] = excl_why

    # ── Step 3: Build cleaned dataset ─────────────────────────────────────────
    cleaned = raw.drop(index=list(seen)).copy()

    # Treat remaining NaN payment amounts as 0 (scheduled but unpaid)
    cleaned["Payment_Amount"] = cleaned["Payment_Amount"].fillna(0.0)

    # Derived columns
    cleaned["Months_on_Book"] = (
        _mob_series(cleaned).clip(lower=0).astype(int)
    )
    cleaned["Cohort"] = (
        cleaned["Origination_Date"].dt.to_period("M").astype(str)
    )

    # ── Console diagnostics ───────────────────────────────────────────────────
    print(f"  Raw rows            : {n_raw:>7,}")
    print(f"  Exact duplicates    : {n_dupes:>7,}  (removed)")
    print(f"  Anomalous/excluded  : {len(excluded):>7,}  rows")
    print(f"  Cleaned rows        : {len(cleaned):>7,}")
    print(f"  Unique cohorts      : {cleaned['Cohort'].nunique():>7}")
    print(f"  Unique assets       : {cleaned['Asset_ID'].nunique():>7}")

    if len(excluded):
        print("\n  Exclusion breakdown:")
        for reason, cnt in excluded["Exclusion_Reason"].value_counts().items():
            print(f"    {cnt:>4}  {reason}")

    return cleaned, excluded


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 · MOIC COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════════

def compute_moic(cleaned: pd.DataFrame) -> tuple:
    """
    Aggregate collections by cohort × months-on-book and compute:

      Payment_MOIC    = Period_Collections   / Cohort_Total_Advance
      Cumulative_MOIC = Running_Collections  / Cohort_Total_Advance

    Design decisions
    ----------------
    1. Only rows with Payment_Amount > 0 feed into MOIC aggregation.
       Zero-amount rows (scheduled-but-unpaid instalment slots) are excluded
       so future scheduled slots don't extend the curve with spurious zeros.
    2. After aggregation, missing MOB months WITHIN each cohort's observed range
       are forward-filled with Period_Collections = 0 so the cumulative curve
       shows flat segments (no collection) instead of omitting those months.

    Returns
    -------
    moic_df     : pd.DataFrame – long form MOIC table (cohort × MOB)
    cohort_meta : pd.DataFrame – cohort-level advance & asset count
    """
    # ── Per-asset advance (constant per asset; take first occurrence) ─────────
    asset_meta = (
        cleaned.groupby("Asset_ID")
               .agg(Cohort        = ("Cohort",         "first"),
                    Total_Advance = ("Total_Advance",  "first"))
               .reset_index()
    )

    # ── Cohort-level metadata ─────────────────────────────────────────────────
    cohort_meta = (
        asset_meta.groupby("Cohort")
                  .agg(Asset_Count          = ("Asset_ID",      "count"),
                       Cohort_Total_Advance = ("Total_Advance", "sum"))
                  .reset_index()
    )

    # ── Aggregate actual (positive) payments only ─────────────────────────────
    paid = cleaned[cleaned["Payment_Amount"] > 0].copy()

    agg = (
        paid.groupby(["Cohort", "Months_on_Book"])["Payment_Amount"]
            .sum()
            .reset_index()
            .rename(columns={"Payment_Amount": "Period_Collections"})
    )
    agg = agg.sort_values(["Cohort", "Months_on_Book"]).reset_index(drop=True)

    # ── Fill missing MOB months within each cohort's observed range ───────────
    ranges = agg.groupby("Cohort")["Months_on_Book"].agg(["min", "max"]).reset_index()
    full_grid = pd.concat(
        [
            pd.DataFrame({
                "Cohort":         row.Cohort,
                "Months_on_Book": range(int(row["min"]), int(row["max"]) + 1),
            })
            for _, row in ranges.iterrows()
        ],
        ignore_index=True,
    )
    agg = full_grid.merge(agg, on=["Cohort", "Months_on_Book"], how="left")
    agg["Period_Collections"] = agg["Period_Collections"].fillna(0.0)

    # ── Merge cohort advance ──────────────────────────────────────────────────
    agg = agg.merge(
        cohort_meta[["Cohort", "Cohort_Total_Advance"]], on="Cohort", how="left"
    )
    agg = agg.sort_values(["Cohort", "Months_on_Book"]).reset_index(drop=True)

    # ── MOIC metrics ──────────────────────────────────────────────────────────
    agg["Payment_MOIC"] = (
        agg["Period_Collections"] / agg["Cohort_Total_Advance"]
    )
    agg["Cumulative_Collections"] = (
        agg.groupby("Cohort")["Period_Collections"].cumsum()
    )
    agg["Cumulative_MOIC"] = (
        agg["Cumulative_Collections"] / agg["Cohort_Total_Advance"]
    )

    print(f"  Cohorts in MOIC table : {agg['Cohort'].nunique()}")
    print(f"  Max Months on Book    : {agg['Months_on_Book'].max()}")
    print(
        f"  Max Cumulative MOIC   : "
        f"{agg['Cumulative_MOIC'].max():.4f}×"
        f"  (cohort {agg.loc[agg['Cumulative_MOIC'].idxmax(), 'Cohort']})"
    )

    return agg, cohort_meta


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 · SUMMARY TABLES
# ═══════════════════════════════════════════════════════════════════════════════

def build_tables(moic_df: pd.DataFrame, cohort_meta: pd.DataFrame) -> tuple:
    """
    Construct three deliverable tables.

    Returns
    -------
    summary     : pd.DataFrame – one-row-per-cohort KPI summary
    cum_matrix  : pd.DataFrame – wide pivot  cohort × MOB → Cumulative MOIC
    pay_matrix  : pd.DataFrame – wide pivot  cohort × MOB → Payment MOIC
    """
    # ── Cohort KPI summary ────────────────────────────────────────────────────
    kpis = (
        moic_df.groupby("Cohort")
               .agg(
                   Total_Collected     = ("Period_Collections", "sum"),
                   Max_Months_on_Book  = ("Months_on_Book",     "max"),
                   Max_Cumulative_MOIC = ("Cumulative_MOIC",    "max"),
                   Avg_Payment_MOIC    = ("Payment_MOIC",       "mean"),
               )
               .reset_index()
    )
    summary = cohort_meta.merge(kpis, on="Cohort", how="left").sort_values("Cohort")

    # Reorder for readability
    summary = summary[[
        "Cohort", "Asset_Count", "Cohort_Total_Advance",
        "Total_Collected", "Max_Months_on_Book",
        "Max_Cumulative_MOIC", "Avg_Payment_MOIC",
    ]]

    # ── Pivot: Cumulative MOIC ────────────────────────────────────────────────
    cum_matrix = (
        moic_df.pivot_table(
            index="Cohort", columns="Months_on_Book",
            values="Cumulative_MOIC", aggfunc="first",
        )
        .reset_index()
    )
    cum_matrix.columns.name = None
    cum_matrix.columns = (
        ["Cohort"] + [f"MOB_{c}" for c in cum_matrix.columns[1:]]
    )

    # ── Pivot: Payment MOIC ───────────────────────────────────────────────────
    pay_matrix = (
        moic_df.pivot_table(
            index="Cohort", columns="Months_on_Book",
            values="Payment_MOIC", aggfunc="first",
        )
        .reset_index()
    )
    pay_matrix.columns.name = None
    pay_matrix.columns = (
        ["Cohort"] + [f"MOB_{c}" for c in pay_matrix.columns[1:]]
    )

    return summary, cum_matrix, pay_matrix


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 · CHART
# ═══════════════════════════════════════════════════════════════════════════════

def plot_moic_curves(moic_df: pd.DataFrame, output_path: str) -> None:
    """
    Render one vintage MOIC curve per origination cohort.

    Chart spec
    ----------
    X-axis : Months on Book (integer)
    Y-axis : Cumulative MOIC (formatted as 0.00×)
    Lines  : one per origination cohort, colour-coded chronologically
    """
    cohorts = sorted(moic_df["Cohort"].unique())
    n       = len(cohorts)

    # Chronological colour gradient (oldest = deep blue, newest = bright yellow)
    PALETTE = plt.cm.turbo(np.linspace(0.10, 0.92, n))

    # ── Theme constants ───────────────────────────────────────────────────────
    BG       = "#0d1117"
    GRID_C   = "#21262d"
    LABEL_C  = "#e6edf3"
    TICK_C   = "#8b949e"
    ANNOT_C  = "#6e7681"

    fig, ax = plt.subplots(figsize=(16, 8))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    # ── Draw one curve per cohort ─────────────────────────────────────────────
    for i, cohort in enumerate(cohorts):
        sub = moic_df[moic_df["Cohort"] == cohort].sort_values("Months_on_Book")
        ax.plot(
            sub["Months_on_Book"],
            sub["Cumulative_MOIC"],
            marker="o",
            markersize=4.5,
            linewidth=2.0,
            color=PALETTE[i],
            label=cohort,
            alpha=0.92,
            zorder=3,
            markeredgewidth=0.6,
            markeredgecolor="#00000033",
        )

    # ── Reference lines ───────────────────────────────────────────────────────
    y_max = moic_df["Cumulative_MOIC"].max()
    for ref_y, ref_label in [
        (1.0, "Break-even  1.00×"),
        (1.3, "Target  1.30×"),
    ]:
        if ref_y <= y_max * 1.12:
            ax.axhline(
                ref_y, color="#cccccc", linestyle="--",
                linewidth=0.85, alpha=0.35, zorder=2,
            )
            ax.text(
                0.006, ref_y + 0.008,
                ref_label,
                transform=ax.get_yaxis_transform(),
                color=ANNOT_C, fontsize=8.5, va="bottom",
            )

    # ── Axis labels & title ───────────────────────────────────────────────────
    ax.set_xlabel("Months on Book (MOB)", color=LABEL_C, fontsize=12, labelpad=10)
    ax.set_ylabel("Cumulative MOIC", color=LABEL_C, fontsize=12, labelpad=10)
    ax.set_title(
        "SahajMobile — Vintage MOIC Curves by Origination Cohort",
        color="white", fontsize=14, fontweight="bold", pad=18,
    )

    # ── Tick formatting ───────────────────────────────────────────────────────
    ax.tick_params(colors=TICK_C, labelsize=9.5)
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda y, _: f"{y:.2f}×")
    )
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.set_ylim(bottom=0)
    ax.set_xlim(left=0)

    # ── Grid & spines ─────────────────────────────────────────────────────────
    for spine in ax.spines.values():
        spine.set_edgecolor("#30363d")
    ax.grid(True, color=GRID_C, linestyle="--", linewidth=0.65, zorder=1)

    # ── Footer annotation ─────────────────────────────────────────────────────
    fig.text(
        0.5, 0.01,
        f"Only actual collections (Payment_Amount > 0) are included  |  "
        f"{n} origination cohorts  |  "
        f"Dashed lines: break-even (1.00×) and target (1.30×)",
        ha="center", color=ANNOT_C, fontsize=8,
    )

    # ── Legend (outside chart, right side) ───────────────────────────────────
    leg = ax.legend(
        title="Origination\nCohort",
        title_fontsize=9,
        fontsize=8.5,
        ncol=1,
        framealpha=0.25,
        edgecolor="#444c56",
        facecolor="#161b22",
        labelcolor="white",
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        borderaxespad=0,
        handlelength=1.8,
        handleheight=1.0,
    )
    leg.get_title().set_color(TICK_C)

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    plt.savefig(
        output_path, dpi=150, bbox_inches="tight",
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)
    print(f"  Saved → {output_path}")


def plot_executive_dashboard(
    moic_df: pd.DataFrame, cohort_summary: pd.DataFrame, output_path: str
) -> None:
    """
    Render an executive-style dashboard with curve, heatmap, ranking, and KPI panels.
    """
    cohorts = sorted(moic_df["Cohort"].unique())
    curve_matrix = (
        moic_df.pivot_table(
            index="Cohort",
            columns="Months_on_Book",
            values="Cumulative_MOIC",
            aggfunc="first",
        )
        .reindex(cohorts)
    )

    latest_rows = (
        moic_df.sort_values(["Cohort", "Months_on_Book"])
              .groupby("Cohort", as_index=False)
              .tail(1)
              [["Cohort", "Months_on_Book", "Cumulative_MOIC"]]
    )
    latest_rows = cohort_summary.merge(latest_rows, on="Cohort", how="left")
    latest_rows["Recovery_Spread"] = (
        latest_rows["Total_Collected"] - latest_rows["Cohort_Total_Advance"]
    )

    peak_row = cohort_summary.loc[cohort_summary["Max_Cumulative_MOIC"].idxmax()]
    recovery_rate = (
        cohort_summary["Total_Collected"].sum()
        / cohort_summary["Cohort_Total_Advance"].sum()
    )

    BG       = "#0b1020"
    PANEL_BG = "#111827"
    GRID_C   = "#293241"
    LABEL_C  = "#e5e7eb"
    TICK_C   = "#9ca3af"
    POS_C    = "#22c55e"
    NEG_C    = "#ef4444"

    fig = plt.figure(figsize=(21, 13), facecolor=BG)
    gs = fig.add_gridspec(
        2,
        2,
        width_ratios=(1.35, 1.0),
        height_ratios=(1.15, 0.85),
        wspace=0.16,
        hspace=0.20,
    )
    ax_curve = fig.add_subplot(gs[0, 0])
    ax_heat = fig.add_subplot(gs[0, 1])
    ax_rank = fig.add_subplot(gs[1, 0])
    ax_kpi = fig.add_subplot(gs[1, 1])

    for ax in (ax_curve, ax_heat, ax_rank, ax_kpi):
        ax.set_facecolor(PANEL_BG)
        for spine in ax.spines.values():
            spine.set_edgecolor("#334155")

    palette = plt.cm.turbo(np.linspace(0.10, 0.92, len(cohorts)))

    for i, cohort in enumerate(cohorts):
        cohort_slice = moic_df[moic_df["Cohort"] == cohort].sort_values("Months_on_Book")
        ax_curve.plot(
            cohort_slice["Months_on_Book"],
            cohort_slice["Cumulative_MOIC"],
            linewidth=2.2,
            marker="o",
            markersize=3.8,
            color=palette[i],
            alpha=0.94,
            label=cohort,
        )

    ax_curve.axhline(1.0, color="#94a3b8", linestyle="--", linewidth=1.0, alpha=0.6)
    ax_curve.axhline(1.3, color="#f59e0b", linestyle="--", linewidth=1.0, alpha=0.7)
    ax_curve.set_title(
        "Vintage Cumulative MOIC Curves",
        color=LABEL_C,
        fontsize=14,
        fontweight="bold",
        pad=12,
    )
    ax_curve.set_xlabel("Months on Book", color=LABEL_C, fontsize=11)
    ax_curve.set_ylabel("Cumulative MOIC", color=LABEL_C, fontsize=11)
    ax_curve.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.2f}×"))
    ax_curve.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax_curve.tick_params(colors=TICK_C, labelsize=9)
    ax_curve.grid(True, color=GRID_C, linestyle="--", linewidth=0.6, alpha=0.8)
    ax_curve.legend(
        title="Cohort",
        fontsize=8,
        title_fontsize=9,
        framealpha=0.20,
        facecolor=PANEL_BG,
        edgecolor="#475569",
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
    )

    heat_data = np.ma.masked_invalid(curve_matrix.to_numpy(dtype=float))
    heat_map = ax_heat.imshow(
        heat_data,
        aspect="auto",
        cmap=plt.cm.magma,
        interpolation="nearest",
        vmin=0,
        vmax=np.nanmax(curve_matrix.to_numpy(dtype=float)),
    )
    ax_heat.set_title(
        "Cumulative MOIC Heatmap",
        color=LABEL_C,
        fontsize=14,
        fontweight="bold",
        pad=12,
    )
    ax_heat.set_xlabel("Months on Book", color=LABEL_C, fontsize=11)
    ax_heat.set_ylabel("Cohort", color=LABEL_C, fontsize=11)
    x_positions = np.arange(len(curve_matrix.columns))
    x_labels = [f"MOB {c}" for c in curve_matrix.columns]
    step = max(1, len(x_positions) // 10)
    ax_heat.set_xticks(x_positions[::step])
    ax_heat.set_xticklabels(x_labels[::step], rotation=45, ha="right", color=TICK_C, fontsize=8)
    ax_heat.set_yticks(np.arange(len(curve_matrix.index)))
    ax_heat.set_yticklabels(curve_matrix.index, color=TICK_C, fontsize=8)
    ax_heat.tick_params(length=0)
    cbar = fig.colorbar(heat_map, ax=ax_heat, fraction=0.046, pad=0.03)
    cbar.ax.tick_params(colors=TICK_C, labelsize=8)
    cbar.set_label("Cumulative MOIC", color=LABEL_C, fontsize=9)

    ranked = latest_rows.sort_values("Max_Cumulative_MOIC", ascending=True)
    bar_colors = [POS_C if value >= 1.0 else NEG_C for value in ranked["Max_Cumulative_MOIC"]]
    ax_rank.barh(ranked["Cohort"], ranked["Max_Cumulative_MOIC"], color=bar_colors, alpha=0.9)
    ax_rank.axvline(1.0, color="#cbd5e1", linestyle="--", linewidth=1.0, alpha=0.7)
    ax_rank.set_title(
        "Cohort Recovery Strength",
        color=LABEL_C,
        fontsize=14,
        fontweight="bold",
        pad=12,
    )
    ax_rank.set_xlabel("Maximum Cumulative MOIC", color=LABEL_C, fontsize=11)
    ax_rank.tick_params(colors=TICK_C, labelsize=9)
    ax_rank.grid(True, axis="x", color=GRID_C, linestyle="--", linewidth=0.6, alpha=0.8)
    for idx, value in enumerate(ranked["Max_Cumulative_MOIC"]):
        ax_rank.text(value + 0.015, idx, f"{value:.2f}×", va="center", color=LABEL_C, fontsize=8)

    ax_kpi.axis("off")
    ax_kpi.text(
        0.00,
        0.98,
        "Executive Cohort Snapshot",
        transform=ax_kpi.transAxes,
        fontsize=15,
        fontweight="bold",
        color=LABEL_C,
        va="top",
    )
    kpi_box = dict(boxstyle="round,pad=0.55", facecolor="#0f172a", edgecolor="#334155", alpha=0.98)
    ax_kpi.text(0.02, 0.82, f"Cohorts analyzed\n{len(cohorts)}", transform=ax_kpi.transAxes, color=LABEL_C, fontsize=12, bbox=kpi_box)
    ax_kpi.text(0.36, 0.82, f"Recovery rate\n{recovery_rate:.2f}×", transform=ax_kpi.transAxes, color=LABEL_C, fontsize=12, bbox=kpi_box)
    ax_kpi.text(0.70, 0.82, f"Best cohort\n{peak_row['Cohort']} ({peak_row['Max_Cumulative_MOIC']:.2f}×)", transform=ax_kpi.transAxes, color=LABEL_C, fontsize=12, bbox=kpi_box)
    top_collected_cohort = latest_rows.sort_values('Total_Collected', ascending=False).iloc[0]['Cohort']
    ax_kpi.text(0.02, 0.48, f"Top collected cohort\n{top_collected_cohort}", transform=ax_kpi.transAxes, color=LABEL_C, fontsize=12, bbox=kpi_box)
    ax_kpi.text(0.36, 0.48, f"Average max MOIC\n{cohort_summary['Max_Cumulative_MOIC'].mean():.2f}×", transform=ax_kpi.transAxes, color=LABEL_C, fontsize=12, bbox=kpi_box)
    ax_kpi.text(0.70, 0.48, f"Peak month on book\n{int(cohort_summary['Max_Months_on_Book'].max())}", transform=ax_kpi.transAxes, color=LABEL_C, fontsize=12, bbox=kpi_box)
    ax_kpi.text(
        0.02,
        0.15,
        "The dashboard combines vintage curves, cohort density, and ranking signals to support an executive readout.",
        transform=ax_kpi.transAxes,
        color=TICK_C,
        fontsize=10,
        wrap=True,
    )

    fig.suptitle(
        "SahajMobile Cohort MOIC Executive Dashboard",
        color="white",
        fontsize=18,
        fontweight="bold",
        y=0.98,
    )
    fig.text(
        0.5,
        0.01,
        "Curves show cumulative collection build-up; heatmap shows cohort aging; ranking and KPIs support rapid portfolio review.",
        ha="center",
        color=TICK_C,
        fontsize=9,
    )

    plt.tight_layout(rect=[0, 0.03, 1, 0.96])
    plt.savefig(
        output_path,
        dpi=160,
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)
    print(f"  Saved → {output_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 · MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 68)
    print("  SahajMobile · Cohort MOIC Analysis")
    print("=" * 68)

    in_path, out_dir = resolve_paths()
    print(f"  Input   : {in_path}")
    print(f"  Outputs : {out_dir}/")

    # ── 1. Load & Clean ───────────────────────────────────────────────────────
    print("\n[1] Loading & Cleaning ...")
    cleaned, excluded = load_and_clean(in_path)

    # ── 2. Compute MOIC ───────────────────────────────────────────────────────
    print("\n[2] Computing MOIC ...")
    moic_df, cohort_meta = compute_moic(cleaned)

    # ── 3. Build Summary Tables ───────────────────────────────────────────────
    print("\n[3] Building Summary Tables ...")
    summary, cum_matrix, pay_matrix = build_tables(moic_df, cohort_meta)

    # ── 4. Print to console ───────────────────────────────────────────────────
    print("\n" + "─" * 68)
    print("  COHORT SUMMARY TABLE")
    print("─" * 68)
    with pd.option_context(
        "display.float_format", "{:.4f}".format,
        "display.max_columns", 15,
        "display.width", 140,
    ):
        print(summary.to_string(index=False))

    print("\n" + "─" * 68)
    print("  CUMULATIVE MOIC MATRIX  (cohort × months on book)")
    print("─" * 68)
    with pd.option_context("display.float_format", "{:.4f}".format, "display.width", 200):
        print(cum_matrix.to_string(index=False))

    # ── 4. Plot ───────────────────────────────────────────────────────────────
    print("\n[4] Plotting MOIC Curves ...")
    plot_moic_curves(moic_df, f"{out_dir}/moic_curve.png")

    print("\n[5] Building Executive Dashboard ...")
    plot_executive_dashboard(moic_df, summary, f"{out_dir}/moic_dashboard.png")

    # ── 6. Save all outputs ───────────────────────────────────────────────────
    print("\n[6] Saving Outputs ...")
    outputs = {
        "cleaned_installments.csv"   : cleaned,
        "excluded_rows.csv"          : excluded,
        "moic_table.csv"             : moic_df,
        "cohort_summary.csv"         : summary,
        "cumulative_moic_matrix.csv" : cum_matrix,
        "payment_moic_matrix.csv"    : pay_matrix,
    }
    for filename, df in outputs.items():
        df.to_csv(f"{out_dir}/{filename}", index=False)
        print(f"  ✓  {filename:<38}  ({len(df):,} rows)")

    print(f"\n  All outputs → {out_dir}/")
    print("\n[Done] ✓")

    return cleaned, excluded, moic_df, summary, cum_matrix, pay_matrix


if __name__ == "__main__":
    main()