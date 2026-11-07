from __future__ import annotations

from waker import globs


def test_single_star_does_not_cross_directories():
    assert globs.matches("src/a.py", "src/*.py")
    assert not globs.matches("src/a/b.py", "src/*.py")


def test_double_star_matches_nested():
    assert globs.matches("src/a.py", "src/**")
    assert globs.matches("src/a/b/c.py", "src/**")


def test_directory_pattern_matches_subtree():
    assert globs.matches("docs/api/readme.md", "docs/api")
    assert not globs.matches("docs/other/readme.md", "docs/api")


def test_trailing_slash_means_subtree():
    assert globs.matches("docs/api/x.md", "docs/api/")


def test_filters_and_normalises_windows_paths():
    files = ["src\\auth\\guard.py", "src/pay/api.py"]
    assert globs.filter_paths(files, ["src/auth/**"]) == ["src\\auth\\guard.py"]


def test_overlap_detection():
    assert globs.overlaps("src/**", "src/pay/**")
    assert globs.overlaps("src/auth/**", "src/auth/**")
    assert not globs.overlaps("src/auth/**", "src/pay/**")
