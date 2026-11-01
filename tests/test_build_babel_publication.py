from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

import build_babel  # noqa: E402


def _write(root: Path, rel: str, content: bytes = b"<html></html>") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "--quiet")
    _write(
        root,
        ".gitignore",
        b"/index.html\n/babel/0_pgs-index/\n/babel/es/01_tdc_entrada/\n/babel/es/02_tdc_salida/\n",
    )


def _track(root: Path, rel: str) -> None:
    blob = _git(root, "hash-object", "-w", "--", rel)
    _git(root, "update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}")


def _assets(root: Path) -> None:
    _write(root, "ux/assets/Open eyes.PNG", b"mascot")
    _write(root, "ux/assets/open eye.png", b"favicon")
    for codes in ("es co mx ar cl us gb ca au nz fr be ch pt br").split():
        _write(root, f"ux/assets/flags/{codes}.svg", b"<svg></svg>")


def _candidate_repo(root: Path) -> tuple[str, ...]:
    _init_repo(root)
    tracked = "babel/es/01_nombre_del_domino_entrada/tracked.html"
    deleted = "babel/es/deleted.html"
    derived = "babel/0_pgs-index/es/index.html"
    _write(root, tracked)
    _write(root, deleted)
    _write(root, derived)
    _track(root, tracked)
    _track(root, deleted)
    _track(root, derived)
    (root / deleted).unlink()
    new_path = "babel/es/01_nombre_del_domino_entrada/new.html"
    _write(root, new_path)
    _write(root, "babel/es/01_tdc_entrada/private.html")
    _write(root, "babel/es/02_tdc_salida/local.html")
    _write(root, "babel/es/01_tdc_entrada/reference.pdf", b"reference")
    outside = _write(root.parent, "outside.html")
    link = root / "babel/es/01_nombre_del_domino_entrada/escape.html"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this environment")
    return tracked, new_path


def _artifact_paths(root: Path) -> tuple[str, ...]:
    return tuple(
        f"{build_babel.BABEL_DIR}/{lang.code}/{artifact.rel}"
        for lang in build_babel.discover(root)
        for artifact in lang.artifacts
    )


def test_discovery_uses_git_visible_html_and_rejects_local_material(tmp_path):
    root = tmp_path / "candidate"
    tracked, new_path = _candidate_repo(root)

    assert _artifact_paths(root) == tuple(sorted((tracked, new_path)))


def test_site_stages_only_publishable_html_and_required_assets(tmp_path):
    root = tmp_path / "candidate"
    tracked, new_path = _candidate_repo(root)
    _assets(root)
    site = tmp_path / "site"

    assert build_babel.main(["--root", str(root), "--site", str(site)]) == 0
    staged = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}
    expected_sources = {tracked, new_path}
    assert expected_sources <= staged
    assert "babel/es/01_tdc_entrada/private.html" not in staged
    assert "babel/es/02_tdc_salida/local.html" not in staged
    assert "babel/es/01_tdc_entrada/reference.pdf" not in staged
    assert "babel/es/01_nombre_del_domino_entrada/escape.html" not in staged
    assert "index.html" in staged
    assert "babel/0_pgs-index/es/index.html" in staged
    assert "ux/assets/Open eyes.PNG" in staged
    assert "ux/assets/open eye.png" in staged
    assert build_babel.main(["--root", str(root), "--site", str(site), "--check"]) == 0

    _write(site, "babel/es/stale.html")
    assert build_babel.main(["--root", str(root), "--site", str(site), "--check"]) == 1


def test_candidate_model_matches_clean_checkout_of_visible_paths(tmp_path):
    candidate = tmp_path / "candidate"
    visible = _candidate_repo(candidate)
    _assets(candidate)
    clean = tmp_path / "clean"
    _init_repo(clean)

    for rel in (*visible, "ux/assets/Open eyes.PNG", "ux/assets/open eye.png"):
        _write(clean, rel, (candidate / rel).read_bytes())
        _track(clean, rel)
    for flag in (candidate / "ux/assets/flags").glob("*.svg"):
        rel = flag.relative_to(candidate).as_posix()
        _write(clean, rel, flag.read_bytes())
        _track(clean, rel)

    assert _artifact_paths(candidate) == _artifact_paths(clean)
    candidate_site = tmp_path / "candidate-site"
    clean_site = tmp_path / "clean-site"
    assert build_babel.main(["--root", str(candidate), "--site", str(candidate_site)]) == 0
    assert build_babel.main(["--root", str(clean), "--site", str(clean_site)]) == 0
    candidate_files = {p.relative_to(candidate_site).as_posix(): p.read_bytes() for p in candidate_site.rglob("*") if p.is_file()}
    clean_files = {p.relative_to(clean_site).as_posix(): p.read_bytes() for p in clean_site.rglob("*") if p.is_file()}
    assert candidate_files == clean_files
