from __future__ import annotations

from scripts import publish


def test_cmd_tag_push_requires_local_tag(monkeypatch) -> None:
    monkeypatch.setattr(publish, "_current_version_or_die", lambda: "0.3.0")
    monkeypatch.setattr(publish, "_local_tag_exists", lambda tag: False)

    rc = publish._cmd_tag_push()

    assert rc == 1


def test_cmd_tag_push_pushes_existing_local_tag(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(publish, "_current_version_or_die", lambda: "0.3.0")
    monkeypatch.setattr(publish, "_local_tag_exists", lambda tag: tag == "v0.3.0")
    monkeypatch.setattr(
        publish,
        "_git_run",
        lambda args: calls.append(args) or 0,
    )

    rc = publish._cmd_tag_push()

    assert rc == 0
    assert calls == [["push", "origin", "v0.3.0"]]


def test_cmd_tag_delete_remote_skips_missing_remote(monkeypatch) -> None:
    monkeypatch.setattr(publish, "_current_version_or_die", lambda: "0.3.0")
    monkeypatch.setattr(publish, "_remote_tag_exists", lambda tag: False)

    rc = publish._cmd_tag_delete_remote()

    assert rc == 0


def test_cmd_tag_delete_remote_deletes_remote_only(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(publish, "_current_version_or_die", lambda: "0.3.0")
    monkeypatch.setattr(publish, "_remote_tag_exists", lambda tag: tag == "v0.3.0")
    monkeypatch.setattr(
        publish,
        "_git_run",
        lambda args: calls.append(args) or 0,
    )

    rc = publish._cmd_tag_delete_remote()

    assert rc == 0
    assert calls == [["push", "origin", "--delete", "v0.3.0"]]
