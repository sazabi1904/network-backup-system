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


def test_full_menu_shows_six_entries(monkeypatch, capsys):
    _scripted_input(monkeypatch, ["0"])
    main.run_full_menu()
    out = capsys.readouterr().out
    for line in ("1. TV1", "2. TV2", "3. TV3", "4. TV4", "5. TV5", "0. Tho"):
        assert line in out


def test_tv1_self_test_then_back(monkeypatch, capsys):
    # menu chung: 1 (TV1); TV1: 1 (self-test); pause: Enter; TV1: 0 (quay lai); menu chung: 0 (thoat)
    prompts = _scripted_input(monkeypatch, ["1", "1", "", "0", "0"])
    main.run_full_menu()
    assert len(prompts) == 5
    assert "[TV1] Ket qua:" in capsys.readouterr().out
