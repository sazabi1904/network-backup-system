import builtins

import main


def test_no_arguments_opens_demo_menu_and_exits(monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "0")
    main.main([])
    out = capsys.readouterr().out
    assert "FAKE DEMO" in out
    assert "usage:" not in out


def test_demo_menu_runs_one_choice_then_returns(monkeypatch, capsys):
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return "1"

    monkeypatch.setattr(builtins, "input", fake_input)
    main.main([])
    assert len(prompts) == 1
    assert "FAKE DEMO" in capsys.readouterr().out
