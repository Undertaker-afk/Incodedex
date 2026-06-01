"""Language-agnostic symbol extraction over a tree-sitter AST.

Produces, per file: a list of definition symbols (functions, classes, methods,
interfaces) with spans/signatures, the calls made inside each symbol, the
base types each class declares (for inheritance), and the file's imports.
The :mod:`graphindex.graph.builder` turns these into graph nodes and edges and
the :mod:`graphindex.graph.resolver` links them across files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ast_parser import node_text, parse
from .grammars import GrammarSpec, get_grammar_spec

_NAME_NODE_TYPES = {"identifier", "type_identifier", "field_identifier",
                    "constant", "property_identifier", "name"}


@dataclass
class ParsedSymbol:
    kind: str
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    signature: str
    node_type: str
    parent: str | None = None         # qualified name of enclosing symbol
    bases: list[str] = field(default_factory=list)   # inheritance targets
    calls: list[str] = field(default_factory=list)   # callee names
    code: str = ""


@dataclass
class ParsedImport:
    raw: str
    modules: list[str]
    line: int


@dataclass
class ParsedFile:
    grammar: str
    symbols: list[ParsedSymbol] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)
    # calls/references made at module top level (no enclosing symbol)
    module_calls: list[str] = field(default_factory=list)
    ok: bool = True


def _first_name(node: Any, source: bytes, name_field: str) -> str:
    child = node.child_by_field_name(name_field)
    if child is not None:
        # For dotted names take the last component.
        text = node_text(child, source)
        return text.split(".")[-1].split("::")[-1].strip()
    # Fallback: first identifier-like descendant.
    for c in node.children:
        if c.type in _NAME_NODE_TYPES:
            return node_text(c, source)
    for c in node.children:
        if c.is_named:
            found = _first_name(c, source, name_field)
            if found:
                return found
    return ""


def _signature(node: Any, source: bytes) -> str:
    text = node_text(node, source)
    line = text.splitlines()[0] if text else ""
    return line[:200]


def _collect_identifiers(node: Any, source: bytes, out: list[str]) -> None:
    if node.type in _NAME_NODE_TYPES:
        out.append(node_text(node, source))
        return
    for c in node.children:
        if c.is_named:
            _collect_identifiers(c, source, out)


def _extract_bases(node: Any, source: bytes, grammar: str) -> list[str]:
    """Collect base/super types declared by a class-like node."""
    bases: list[str] = []
    for field_name in ("superclasses", "superclass", "interfaces",
                        "super_interfaces", "trait", "type"):
        child = node.child_by_field_name(field_name)
        if child is not None:
            _collect_identifiers(child, source, bases)
    # Generic heuristics for grammars without those fields.
    for c in node.children:
        if c.type in {"class_heritage", "extends_clause", "implements_clause",
                      "base_class_clause"}:
            _collect_identifiers(c, source, bases)
    # Deduplicate, drop the class's own name handled by caller.
    seen, result = set(), []
    for b in bases:
        b = b.strip()
        if b and b not in seen:
            seen.add(b)
            result.append(b)
    return result


def _callee_name(call_node: Any, source: bytes, spec: GrammarSpec) -> str:
    target = call_node.child_by_field_name(spec.callee_field)
    if target is None:
        # Fallback: first child that's a name/attribute.
        for c in call_node.children:
            if c.is_named and c.type not in {"arguments", "argument_list"}:
                target = c
                break
    if target is None:
        return ""
    text = node_text(target, source)
    # a.b.c(...) / a::b::c(...) -> c ; this[...] -> ''
    text = text.split("(")[0]
    for sep in (".", "::", "->"):
        if sep in text:
            text = text.split(sep)[-1]
    return text.strip().strip("!")  # rust macro names keep '!' stripped


def _import_modules(node: Any, source: bytes, grammar: str) -> list[str]:
    raw = node_text(node, source)
    mods: list[str] = []
    # dotted_name / module names live in identifier-ish descendants
    for c in node.children:
        if c.type in {"dotted_name", "scoped_identifier", "import_spec",
                      "string", "interpreted_string_literal", "string_literal",
                      "identifier", "scoped_use_list", "use_wildcard"}:
            txt = node_text(c, source).strip("\"'`;")
            if txt:
                mods.append(txt.split()[0])
    if not mods:
        # crude fallback: take token after import/from/use/require
        tokens = raw.replace(";", " ").split()
        for kw in ("from", "import", "use", "require"):
            if kw in tokens:
                idx = tokens.index(kw)
                if idx + 1 < len(tokens):
                    mods.append(tokens[idx + 1].strip("\"'`(),"))
                break
    return [m for m in dict.fromkeys(mods) if m]


def extract_symbols(grammar: str, source: bytes) -> ParsedFile:
    spec = get_grammar_spec(grammar)
    tree = parse(grammar, source)
    if spec is None or tree is None:
        return ParsedFile(grammar=grammar, ok=False)

    pf = ParsedFile(grammar=grammar)
    root = tree.root_node

    def walk(node: Any, scope: ParsedSymbol | None, qual_prefix: str) -> None:
        ntype = node.type
        new_scope = scope

        if ntype in spec.def_types:
            name = _first_name(node, source, spec.name_field)
            kind = spec.def_types[ntype]
            # function defined inside a class becomes a method
            if kind == "function" and scope is not None and scope.kind in {
                    "class", "interface"}:
                kind = "method"
            qualified = f"{qual_prefix}.{name}" if qual_prefix and name else (name or qual_prefix)
            sym = ParsedSymbol(
                kind=kind, name=name or "<anon>", qualified_name=qualified,
                start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                signature=_signature(node, source), node_type=ntype,
                parent=scope.qualified_name if scope else None,
                code=node_text(node, source),
            )
            if ntype in spec.class_types:
                sym.bases = [b for b in _extract_bases(node, source, grammar) if b != name]
            pf.symbols.append(sym)
            new_scope = sym
            qual_prefix = qualified

        elif ntype in spec.call_types:
            callee = _callee_name(node, source, spec)
            if callee:
                if scope is not None:
                    scope.calls.append(callee)
                else:
                    pf.module_calls.append(callee)

        elif ntype in spec.import_types:
            mods = _import_modules(node, source, grammar)
            pf.imports.append(ParsedImport(
                raw=_signature(node, source), modules=mods,
                line=node.start_point[0] + 1))

        for child in node.children:
            if child.is_named:
                walk(child, new_scope, qual_prefix)

    walk(root, None, "")
    return pf
