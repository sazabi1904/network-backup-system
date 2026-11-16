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


def test_no_arguments_opens_full_menu_and_exits(monkeypatch, capsys):
    _scripted_input(monkeypatch, ["0"])
    main.main([])
    out = capsys.readouterr().out
    assert "MENU CHUNG" in out
    assert "usage:" not in out


def test_demo_flag_runs_fake_device_menu(monkeypatch, capsys):
    prompts = _scripted_input(monkeypatch, ["0"])
    main.main(["--demo"])
    assert len(prompts) == 1
    assert "FAKE DEMO" in capsys.readouterr().out


def test_self_test_flag_still_works(capsys):
    try:
        main.main(["--self-test"])
    except SystemExit as exc:
        assert exc.code == 0
    assert "PASS" in capsys.readouterr().out
