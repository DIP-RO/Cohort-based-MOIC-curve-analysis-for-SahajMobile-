"""Shared fixtures for the SahajMobile cohort MOIC test suite."""

import importlib
import os
import sys
from pathlib import Path

import matplotlib
import pandas as pd
import pytest

matplotlib.use("Agg")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

moic = importlib.import_module("sahajmobile_moic")


@pytest.fixture()
def module():
    """The module under test."""
    return moic


@pytest.fixture()
def raw_rows():
    """Two clean assets in two cohorts, with messy currency formatting."""
    return [
        # Asset 1 — cohort 2024-01, advance 1,000, pays 600 at MOB 1 and 600 at MOB 3
        {
            "Asset ID": 1,
            "Origination Date": "1/31/2024",
            " Total Advance ": " 1,000 ",
            " Total EMI ": " 1,200 ",
            "Payment Date": "2/7/2024",
            " Payment Amount ": " 600 ",
        },
        {
            "Asset ID": 1,
            "Origination Date": "1/31/2024",
            " Total Advance ": " 1,000 ",
            " Total EMI ": " 1,200 ",
            "Payment Date": "4/7/2024",
            " Payment Amount ": " 600 ",
        },
        # Asset 2 — cohort 2024-02, advance 2,000, pays 500 at MOB 0
        {
            "Asset ID": 2,
            "Origination Date": "2/1/2024",
            " Total Advance ": " 2,000 ",
            " Total EMI ": " 2,400 ",
            "Payment Date": "2/20/2024",
            " Payment Amount ": " 500 ",
        },
        # Asset 2 — scheduled-but-unpaid slot (dash amount)
        {
            "Asset ID": 2,
            "Origination Date": "2/1/2024",
            " Total Advance ": " 2,000 ",
            " Total EMI ": " 2,400 ",
            "Payment Date": "3/20/2024",
            " Payment Amount ": " - ",
        },
    ]


@pytest.fixture()
def csv_path(tmp_path, raw_rows):
    """Write ``raw_rows`` to a CSV using the raw (unstandardised) headers."""

    def _write(rows=None, name="input.csv"):
        path = tmp_path / name
        pd.DataFrame(rows if rows is not None else raw_rows).to_csv(path, index=False)
        return path

    return _write


@pytest.fixture()
def moic_frame(module, csv_path, raw_rows):
    """Long-form MOIC table plus cohort metadata built from the sample rows."""
    cleaned, _ = module.load_and_clean(str(csv_path(raw_rows)))
    return module.compute_moic(cleaned)
