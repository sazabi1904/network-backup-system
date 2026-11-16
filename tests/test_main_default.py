import builtins

import main


def _scripted_input(monkeypatch, answers):
    prompts = []
    queue = list(answers)

    def fake_input(prompt=""):
        prompts.append(prompt)
        return queue.pop(0)

    monkeypatch.setattr(builtins, "input", fake_input)
    return prompts


def test_no_arguments_opens_demo_menu_and_exits(monkeypatch, capsys):
    _scripted_input(monkeypatch, ["0"])
    main.main([])
    out = capsys.readouterr().out
    assert "FAKE DEMO" in out
    assert "usage:" not in out


def test_action_then_other_key_exits(monkeypatch, capsys):
    prompts = _scripted_input(monkeypatch, ["1", "x"])
    main.main([])
    assert len(prompts) == 2
    assert "FAKE DEMO" in capsys.readouterr().out


def test_action_then_zero_returns_to_menu(monkeypatch, capsys):
    prompts = _scripted_input(monkeypatch, ["2", "0", "0"])
    main.main([])
    assert len(prompts) == 3
    assert capsys.readouterr().out.count("FAKE DEMO") == 2
