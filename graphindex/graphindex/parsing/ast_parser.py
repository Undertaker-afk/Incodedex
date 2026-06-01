"""Tree-sitter parser loading using the standard ``tree_sitter`` 0.25 API.

Each grammar is provided by its own pip wheel (``tree-sitter-python`` etc.),
which exposes a ``language()`` PyCapsule consumed by ``tree_sitter.Language``.
Parsers are cached per grammar. Sources are parsed as UTF-8 bytes so that
``node.start_byte``/``end_byte`` slice the original content correctly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable

try:
    from tree_sitter import Language, Parser
    _HAS_TS = True
except Exception:  # pragma: no cover
    Language = Parser = None  # type: ignore
    _HAS_TS = False


def _loader(module: str, attr: str = "language") -> Callable[[], Any]:
    def _load() -> Any:
        mod = __import__(module, fromlist=[attr])
        return getattr(mod, attr)()
    return _load


# grammar name -> callable returning a tree-sitter language capsule
_GRAMMAR_LOADERS: dict[str, Callable[[], Any]] = {
    "python": _loader("tree_sitter_python"),
    "javascript": _loader("tree_sitter_javascript"),
    "typescript": _loader("tree_sitter_typescript", "language_typescript"),
    "tsx": _loader("tree_sitter_typescript", "language_tsx"),
    "go": _loader("tree_sitter_go"),
    "java": _loader("tree_sitter_java"),
    "rust": _loader("tree_sitter_rust"),
    "ruby": _loader("tree_sitter_ruby"),
    "c": _loader("tree_sitter_c"),
    "cpp": _loader("tree_sitter_cpp"),
    "c_sharp": _loader("tree_sitter_c_sharp"),
    "php": _loader("tree_sitter_php", "language_php"),
    "zig": _loader("tree_sitter_zig"),
    "swift": _loader("tree_sitter_swift"),
    "kotlin": _loader("tree_sitter_kotlin"),
    "scala": _loader("tree_sitter_scala"),
    "haskell": _loader("tree_sitter_haskell"),
    "lua": _loader("tree_sitter_lua"),
    "ocaml": _loader("tree_sitter_ocaml"),
    "elixir": _loader("tree_sitter_elixir"),
    "erlang": _loader("tree_sitter_erlang"),
    "clojure": _loader("tree_sitter_clojure"),
    "julia": _loader("tree_sitter_julia"),
    "r": _loader("tree_sitter_r"),
    "perl": _loader("tree_sitter_perl"),
    "bash": _loader("tree_sitter_bash"),
    "sql": _loader("tree_sitter_sql"),
    "nix": _loader("tree_sitter_nix"),
    "dart": _loader("tree_sitter_dart"),
    "elm": _loader("tree_sitter_elm"),
}


def available_grammars() -> list[str]:
    return sorted(_GRAMMAR_LOADERS)


@lru_cache(maxsize=32)
def get_parser(grammar: str) -> Any | None:
    """Return a cached tree-sitter parser for ``grammar`` or None if unavailable."""
    if not _HAS_TS:
        return None
    loader = _GRAMMAR_LOADERS.get(grammar)
    if loader is None:
        return None
    try:
        language = Language(loader())
        return Parser(language)
    except Exception:
        return None


def parse(grammar: str, source: bytes):
    """Parse UTF-8 ``source`` bytes and return a tree-sitter tree, or None."""
    parser = get_parser(grammar)
    if parser is None:
        return None
    if isinstance(source, str):
        source = source.encode("utf-8")
    try:
        return parser.parse(source)
    except Exception:
        return None


def node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
