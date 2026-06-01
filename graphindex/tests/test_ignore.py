from graphindex.scanner.ignore import IgnoreEngine
from graphindex.scanner.walker import RepoScanner


def test_graphignore_excludes_and_negates(sample_repo):
    eng = IgnoreEngine(sample_repo)
    # .graphignore ignores *.log and secret.py, but re-includes keep.py via !
    assert eng.is_ignored("debug.log")
    assert eng.is_ignored("secret.py")
    assert not eng.is_ignored("keep.py")
    assert not eng.is_ignored("pkg/models.py")


def test_always_ignore_dirs(sample_repo):
    eng = IgnoreEngine(sample_repo)
    assert eng.is_ignored(".git/config")
    assert eng.is_ignored("node_modules/x/index.js")


def test_scanner_only_returns_known_languages(sample_repo):
    scanner = RepoScanner(sample_repo)
    paths = {f.rel_path for f in scanner.scan()}
    assert "pkg/models.py" in paths
    assert "app.js" in paths
    assert "debug.log" not in paths   # ignored + unknown language
    assert "secret.py" not in paths   # graphignore
