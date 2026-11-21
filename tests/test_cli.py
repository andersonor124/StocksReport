"""Interactive CLI: ask the user which company to analyse."""
import builtins

import pytest

import cli
from stocksreport.data import lookup as L

APPLE = [L.Match("AAPL", "Apple Inc.", "NMS"), L.Match("APLE", "Apple Hospitality REIT, Inc.", "NYQ")]
BRK = [L.Match("BRK-B", "Berkshire Hathaway Inc. New", "NYQ"), L.Match("BRK-A", "Berkshire Hathaway Inc.", "NYQ")]


@pytest.fixture
def fake(monkeypatch):
    calls = {}
    table = {"apple": APPLE, "aapl": APPLE[:1], "berkshire": BRK, "nvda": [L.Match("NVDA", "NVIDIA Corporation", "NMS")]}
    monkeypatch.setattr(L, "resolve", lambda q, **kw: table.get(q.lower(), []))

    def report(args):
        calls["report"] = (list(args.tickers), list(args.format))
        return 0

    def verify(args):
        calls["verify"] = list(args.tickers)
        return 0
    monkeypatch.setattr(cli, "_report", report)
    monkeypatch.setattr(cli, "_verify", verify)
    monkeypatch.setattr(cli, "_interactive_ok", lambda: True)
    return calls


def answers(monkeypatch, *replies):
    it = iter(replies)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))


def test_no_args_prompts_for_company_and_formats(fake, monkeypatch):
    answers(monkeypatch, "apple", "")  # name, then Enter = all formats
    assert cli.main([]) == 0
    assert fake["report"] == (["AAPL"], ["html", "xlsx", "pptx"])


def test_ambiguous_name_shows_menu(fake, monkeypatch, capsys):
    answers(monkeypatch, "berkshire", "2", "html")
    cli.main([])
    assert fake["report"] == (["BRK-A"], ["html"])
    assert "1) BRK-B" in capsys.readouterr().out


def test_unknown_name_reprompts(fake, monkeypatch, capsys):
    answers(monkeypatch, "xyzzyqq", "nvda", "pptx xlsx")
    cli.main([])
    assert fake["report"] == (["NVDA"], ["pptx", "xlsx"])
    assert "No company found for 'xyzzyqq'" in capsys.readouterr().out


def test_several_companies_at_once(fake, monkeypatch):
    answers(monkeypatch, "apple, nvda", "")
    cli.main([])
    assert fake["report"][0] == ["AAPL", "NVDA"]


def test_q_quits(fake, monkeypatch):
    answers(monkeypatch, "q")
    assert cli.main([]) == 0 and "report" not in fake


def test_names_on_command_line_are_resolved(fake, monkeypatch):
    answers(monkeypatch)  # no prompts expected
    cli.main(["apple", "--format", "html"])
    assert fake["report"] == (["AAPL"], ["html"])


def test_existing_ticker_usage_unchanged(fake, monkeypatch):
    answers(monkeypatch)
    cli.main(["AAPL", "NVDA", "--format", "html", "xlsx"])
    assert fake["report"] == (["AAPL", "NVDA"], ["html", "xlsx"])


def test_verify_prompts_too(fake, monkeypatch):
    answers(monkeypatch, "apple")
    cli.main(["verify"])
    assert fake["verify"] == ["AAPL"]


def test_non_interactive_without_tickers_prints_usage(fake, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_interactive_ok", lambda: False)
    assert cli.main([]) == 2
    assert "python cli.py <company or ticker>" in capsys.readouterr().err
