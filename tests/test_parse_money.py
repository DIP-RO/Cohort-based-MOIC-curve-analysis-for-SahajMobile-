"""Unit tests for the currency parsing helper."""

import numpy as np
import pandas as pd
import pytest


@pytest.mark.parametrize(
    "value, expected",
    [
        (" 17,160 ", 17160.0),
        ("9,000", 9000.0),
        ("1 234", 1234.0),
        ("0", 0.0),
        (1500, 1500.0),
        (1500.75, 1500.75),
        ("1500.75", 1500.75),
    ],
)
def test_parses_numbers_and_thousands_separators(module, value, expected):
    assert module._parse_money(pd.Series([value])).iloc[0] == pytest.approx(expected)


@pytest.mark.parametrize(
    "dash",
    [" - ", "-", "\u2013", "\u2014", "\u2212", " -- ", "."],
)
def test_dash_variants_and_bare_dot_become_zero(module, dash):
    """A dash means the instalment was scheduled but never paid."""
    assert module._parse_money(pd.Series([dash])).iloc[0] == 0.0


def test_negative_amount_loses_its_sign(module):
    """Dash stripping is unconditional, so '-500' parses as 500."""
    assert module._parse_money(pd.Series(["-500"])).iloc[0] == 500.0


@pytest.mark.parametrize("value", [None, np.nan, pd.NA])
def test_missing_values_stay_nan(module, value):
    assert pd.isna(module._parse_money(pd.Series([value], dtype="object")).iloc[0])


@pytest.mark.parametrize("value", ["n/a", "TBD", "1.2.3", "12x"])
def test_unparseable_strings_become_nan(module, value):
    assert pd.isna(module._parse_money(pd.Series([value])).iloc[0])


def test_returns_series_aligned_with_input_index(module):
    series = pd.Series([" 1,000 ", " - ", "bad"], index=[5, 6, 7])
    parsed = module._parse_money(series)

    assert list(parsed.index) == [5, 6, 7]
    assert parsed.iloc[0] == 1000.0
    assert parsed.iloc[1] == 0.0
    assert pd.isna(parsed.iloc[2])


def test_empty_series_returns_empty(module):
    assert module._parse_money(pd.Series([], dtype="object")).empty
