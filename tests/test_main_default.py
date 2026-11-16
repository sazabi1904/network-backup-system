import builtins

import main


def test_no_arguments_opens_demo_menu_and_exits(monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "0")
    main.main([])
    out = capsys.readouterr().out
    assert "FAKE DEMO" in out
    assert "usage:" not in out
