"""Query model + filter-syntax parser.

Supported inline filters (``key:value``) anywhere in the query string:

* ``path:`` substring the file path must contain (also acts as scope)
* ``lang:`` language (python, javascript, ...)
* ``ext:``  file extension (py, ts, ...)
* ``kind:`` node kind (function, class, method, file, ...)
* ``scope:`` restrict to a directory prefix
* ``branch:`` / ``commit:`` restrict to a git commit

Everything else is free text. Modes (regex / semantic / fuzzy / case) are passed
explicitly by the caller (CLI flags, API params).
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

_FILTER_KEYS = {"path", "lang", "language", "ext", "kind", "scope", "branch", "commit"}


@dataclass
class Query:
    text: str = ""
    regex: bool = False
    semantic: bool = False
    fuzzy: bool = False
    case_sensitive: bool = False
    filters: dict[str, str] = field(default_factory=dict)
    scope: str = ""
    branch: str = ""
    top_k: int = 25

    @property
    def language(self) -> str:
        return self.filters.get("lang") or self.filters.get("language") or ""

    @property
    def ext(self) -> str:
        return self.filters.get("ext", "")

    @property
    def kind(self) -> str:
        return self.filters.get("kind", "")

    @property
    def path(self) -> str:
        return self.filters.get("path", "")


def parse_query(raw: str, **modes) -> Query:
    """Extract inline ``key:value`` filters; remaining tokens form the text."""
    filters: dict[str, str] = {}
    text_tokens: list[str] = []
    try:
        tokens = shlex.split(raw)
    except ValueError:
        tokens = raw.split()
    for tok in tokens:
        if ":" in tok:
            key, _, val = tok.partition(":")
            key = key.lower()
            if key in _FILTER_KEYS and val:
                filters[key] = val
                continue
        text_tokens.append(tok)
    q = Query(text=" ".join(text_tokens), filters=filters, **modes)
    q.scope = filters.get("scope", filters.get("path", q.scope))
    q.branch = filters.get("branch", filters.get("commit", q.branch))
    return q
