from __future__ import annotations

from pathlib import Path

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


def test_collect_installer_uses_current_version_when_old_nsis_remains(
    monkeypatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    dist = repo / "dist"
    release_dir = dist / "rosetta-0.3.1"
    target_release = repo / "packages" / "desktop" / "tauri" / "target" / "release"
    nsis_dir = target_release / "bundle" / "nsis"

    dist.mkdir(parents=True)
    nsis_dir.mkdir(parents=True)
    for name in ("rosetta.exe", "rosetta-server.exe"):
        (dist / name).write_text(name, encoding="utf-8")
    (target_release / "rosetta-desktop.exe").write_text("desktop", encoding="utf-8")
    (nsis_dir / "Rosetta_0.3.0_x64-setup.exe").write_text("old", encoding="utf-8")
    (nsis_dir / "Rosetta_0.3.1_x64-setup.exe").write_text("current", encoding="utf-8")
    (nsis_dir / "latest.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(publish, "_REPO_ROOT", repo)
    monkeypatch.setattr(publish, "_DIST_DIR", dist)
    monkeypatch.setattr(publish, "_current_version_or_die", lambda: "0.3.1")
    monkeypatch.setattr(publish, "_cargo_target_release", lambda: target_release)

    publish._collect(release_dir, installer=True)

    assert (release_dir / "Rosetta_0.3.1_x64-setup.exe").read_text(encoding="utf-8") == "current"
    assert not (release_dir / "Rosetta_0.3.0_x64-setup.exe").exists()
