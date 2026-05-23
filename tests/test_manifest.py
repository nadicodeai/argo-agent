"""Tests for argo_sync.manifest — sync manifest writer.

Covers all 10 required test cases:
1. Writing a manifest creates .argo/sync-manifest.json with the expected JSON shape.
2. files_touched is sorted and uses POSIX paths regardless of input order/platform.
3. Duplicate paths in files_touched are deduplicated.
4. ran_at defaults to parseable ISO-8601 UTC; honors override when passed.
5. Round-trip: write then read JSON back; same logical structure.
6. Deterministic output: byte-identical files for identical inputs + identical now=.
7. .argo/ is created if missing.
8. Empty files_touched produces "files_touched": [].
9. exceptions_used is sorted in output.
10. File ends with a trailing newline.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from argo_sync.manifest import ManifestWriter, SyncManifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXED_NOW = "2026-05-24T00:30:00+00:00"
FIXED_SHA = "abc123def456abc123def456abc123def456abc1"


def make_manifest(
    files: tuple[Path, ...] = (),
    exceptions: tuple[str, ...] = (),
    sha: str = FIXED_SHA,
) -> SyncManifest:
    return SyncManifest(
        upstream_sha=sha,
        files_touched=files,
        exceptions_used=exceptions,
    )


# ---------------------------------------------------------------------------
# Test 1: Writing a manifest creates .argo/sync-manifest.json with expected JSON shape
# ---------------------------------------------------------------------------


def test_write_creates_manifest_with_correct_shape(tmp_path: Path) -> None:
    manifest = make_manifest(
        files=(tmp_path / "pkg/module.py", tmp_path / "pkg/other.py"),
        exceptions=(".shepherd/**",),
    )
    writer = ManifestWriter(tmp_path)
    out = writer.write(manifest, now=FIXED_NOW)

    assert out == tmp_path / ".argo" / "sync-manifest.json"
    assert out.exists()

    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"upstream_sha", "ran_at", "files_touched", "exceptions_used"}
    assert data["upstream_sha"] == FIXED_SHA
    assert data["ran_at"] == FIXED_NOW
    assert isinstance(data["files_touched"], list)
    assert isinstance(data["exceptions_used"], list)


# ---------------------------------------------------------------------------
# Test 2: files_touched is sorted alphabetically and uses POSIX paths
# ---------------------------------------------------------------------------


def test_files_touched_sorted_posix_paths(tmp_path: Path) -> None:
    # Provide paths in reverse alphabetical order; expect sorted POSIX output.
    paths = (
        tmp_path / "zzz/last.py",
        tmp_path / "aaa/first.py",
        tmp_path / "mmm/middle.py",
    )
    manifest = make_manifest(files=paths)
    writer = ManifestWriter(tmp_path)
    out = writer.write(manifest, now=FIXED_NOW)

    data = json.loads(out.read_text(encoding="utf-8"))
    touched = data["files_touched"]

    # Verify sorted order
    assert touched == sorted(touched)
    # Verify POSIX forward slashes only
    for entry in touched:
        assert "\\" not in entry, f"Backslash found in path: {entry!r}"


# ---------------------------------------------------------------------------
# Test 3: Duplicate paths in files_touched are deduplicated
# ---------------------------------------------------------------------------


def test_files_touched_deduplication(tmp_path: Path) -> None:
    dup_path = tmp_path / "pkg/module.py"
    paths = (dup_path, dup_path, tmp_path / "other.py")
    manifest = make_manifest(files=paths)
    writer = ManifestWriter(tmp_path)
    out = writer.write(manifest, now=FIXED_NOW)

    data = json.loads(out.read_text(encoding="utf-8"))
    touched = data["files_touched"]
    assert len(touched) == len(set(touched)), "Duplicate paths found in output"


# ---------------------------------------------------------------------------
# Test 4: ran_at defaults to parseable ISO-8601 UTC; honors override
# ---------------------------------------------------------------------------


def test_ran_at_defaults_to_utc_iso8601(tmp_path: Path) -> None:
    manifest = make_manifest()
    writer = ManifestWriter(tmp_path)
    before = datetime.now(timezone.utc)
    out = writer.write(manifest)
    after = datetime.now(timezone.utc)

    data = json.loads(out.read_text(encoding="utf-8"))
    ran_at_str = data["ran_at"]

    # Must be parseable as ISO-8601
    ran_at = datetime.fromisoformat(ran_at_str)
    # Must have timezone info (UTC)
    assert ran_at.tzinfo is not None
    # Must be within the test window
    assert before <= ran_at <= after


def test_ran_at_honors_override(tmp_path: Path) -> None:
    manifest = make_manifest()
    writer = ManifestWriter(tmp_path)
    out = writer.write(manifest, now=FIXED_NOW)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["ran_at"] == FIXED_NOW


# ---------------------------------------------------------------------------
# Test 5: Round-trip — write then read JSON back; same logical structure
# ---------------------------------------------------------------------------


def test_round_trip(tmp_path: Path) -> None:
    files = (tmp_path / "alpha/a.py", tmp_path / "beta/b.py")
    exceptions = ("argo-rename.yaml", ".shepherd/**")
    manifest = make_manifest(files=files, exceptions=exceptions)
    writer = ManifestWriter(tmp_path)
    out = writer.write(manifest, now=FIXED_NOW)

    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["upstream_sha"] == FIXED_SHA
    assert data["ran_at"] == FIXED_NOW
    # files_touched should be relative POSIX paths sorted
    assert sorted(data["files_touched"]) == data["files_touched"]
    # exceptions_used should be sorted
    assert sorted(data["exceptions_used"]) == data["exceptions_used"]
    assert set(data["exceptions_used"]) == set(exceptions)


# ---------------------------------------------------------------------------
# Test 6: Deterministic output — byte-identical for identical inputs
# ---------------------------------------------------------------------------


def test_deterministic_output(tmp_path: Path) -> None:
    dir_a = tmp_path / "run_a"
    dir_b = tmp_path / "run_b"
    dir_a.mkdir()
    dir_b.mkdir()

    files = (tmp_path / "pkg/module.py", tmp_path / "pkg/other.py")
    exceptions = (".shepherd/**", "argo-rename.yaml")
    manifest = make_manifest(files=files, exceptions=exceptions)

    writer_a = ManifestWriter(dir_a)
    writer_b = ManifestWriter(dir_b)

    out_a = writer_a.write(manifest, now=FIXED_NOW)
    out_b = writer_b.write(manifest, now=FIXED_NOW)

    bytes_a = out_a.read_bytes()
    bytes_b = out_b.read_bytes()
    assert bytes_a == bytes_b, "Output differs between two runs with identical inputs"


# ---------------------------------------------------------------------------
# Test 7: .argo/ is created if missing
# ---------------------------------------------------------------------------


def test_argo_dir_created_if_missing(tmp_path: Path) -> None:
    argo_dir = tmp_path / ".argo"
    assert not argo_dir.exists(), "Precondition: .argo must not exist yet"

    manifest = make_manifest()
    writer = ManifestWriter(tmp_path)
    writer.write(manifest, now=FIXED_NOW)

    assert argo_dir.is_dir()
    assert (argo_dir / "sync-manifest.json").exists()


# ---------------------------------------------------------------------------
# Test 8: Empty files_touched produces "files_touched": []
# ---------------------------------------------------------------------------


def test_empty_files_touched(tmp_path: Path) -> None:
    manifest = make_manifest(files=())
    writer = ManifestWriter(tmp_path)
    out = writer.write(manifest, now=FIXED_NOW)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert "files_touched" in data
    assert data["files_touched"] == []


# ---------------------------------------------------------------------------
# Test 9: exceptions_used is sorted in output
# ---------------------------------------------------------------------------


def test_exceptions_used_sorted(tmp_path: Path) -> None:
    # Provide in reverse order; expect sorted in output.
    exceptions = ("zzz/last", "aaa/first", "mmm/middle")
    manifest = make_manifest(exceptions=exceptions)
    writer = ManifestWriter(tmp_path)
    out = writer.write(manifest, now=FIXED_NOW)

    data = json.loads(out.read_text(encoding="utf-8"))
    exc = data["exceptions_used"]
    assert exc == sorted(exc)


# ---------------------------------------------------------------------------
# Test 10: File ends with a trailing newline
# ---------------------------------------------------------------------------


def test_trailing_newline(tmp_path: Path) -> None:
    manifest = make_manifest()
    writer = ManifestWriter(tmp_path)
    out = writer.write(manifest, now=FIXED_NOW)

    raw = out.read_bytes()
    assert raw.endswith(b"\n"), "Manifest file must end with a trailing newline"


# ---------------------------------------------------------------------------
# Bonus: exceptions_used=() (default) produces empty list
# ---------------------------------------------------------------------------


def test_exceptions_used_defaults_to_empty(tmp_path: Path) -> None:
    manifest = SyncManifest(upstream_sha=FIXED_SHA, files_touched=())
    writer = ManifestWriter(tmp_path)
    out = writer.write(manifest, now=FIXED_NOW)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["exceptions_used"] == []
