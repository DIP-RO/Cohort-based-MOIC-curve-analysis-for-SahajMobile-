"""Unit tests for input/output path resolution."""

import pytest


def test_cli_arguments_take_precedence(module, tmp_path, monkeypatch):
    src = tmp_path / "custom.csv"
    src.write_text("Asset ID\n")
    out = tmp_path / "custom-outputs"
    monkeypatch.setattr(module.sys, "argv", ["prog", str(src), str(out)])

    in_path, out_path = module.resolve_paths()

    assert (in_path, out_path) == (str(src), str(out))
    assert out.is_dir()


def test_falls_back_to_module_defaults(module, tmp_path, monkeypatch):
    src = tmp_path / "default.csv"
    src.write_text("Asset ID\n")
    out = tmp_path / "default-outputs"
    monkeypatch.setattr(module.sys, "argv", ["prog"])
    monkeypatch.setattr(module, "INPUT_PATH", str(src))
    monkeypatch.setattr(module, "OUTPUT_DIR", str(out))

    assert module.resolve_paths() == (str(src), str(out))


def test_output_dir_from_default_when_only_input_given(module, tmp_path, monkeypatch):
    src = tmp_path / "only-input.csv"
    src.write_text("Asset ID\n")
    out = tmp_path / "fallback-outputs"
    monkeypatch.setattr(module.sys, "argv", ["prog", str(src)])
    monkeypatch.setattr(module, "OUTPUT_DIR", str(out))

    assert module.resolve_paths() == (str(src), str(out))


def test_existing_output_dir_is_reused(module, tmp_path, monkeypatch):
    src = tmp_path / "input.csv"
    src.write_text("Asset ID\n")
    out = tmp_path / "outputs"
    out.mkdir()
    keep = out / "keep.txt"
    keep.write_text("keep me")
    monkeypatch.setattr(module.sys, "argv", ["prog", str(src), str(out)])

    module.resolve_paths()

    assert keep.read_text() == "keep me"


def test_missing_input_exits_with_code_1(module, tmp_path, monkeypatch, capsys):
    missing = tmp_path / "nope.csv"
    monkeypatch.setattr(module.sys, "argv", ["prog", str(missing)])

    with pytest.raises(SystemExit) as exc:
        module.resolve_paths()

    assert exc.value.code == 1
    assert "Input file not found" in capsys.readouterr().out
