"""Per-grammar configuration driving language-agnostic symbol extraction.

Rather than hand-write tree-sitter queries per language (brittle across grammar
versions), we describe each language by the *node types* that denote
definitions, calls, imports and inheritance. A single generic tree walker
(:mod:`graphindex.parsing.symbols`) consumes this table. Adding a language is
usually just adding a dict entry here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GrammarSpec:
    # node type -> symbol kind
    def_types: dict[str, str] = field(default_factory=dict)
    class_types: set[str] = field(default_factory=set)
    call_types: set[str] = field(default_factory=set)
    import_types: set[str] = field(default_factory=set)
    # field name holding the callee inside a call node (else search identifiers)
    callee_field: str = "function"
    # field name holding the symbol name inside a definition node
    name_field: str = "name"


GRAMMARS: dict[str, GrammarSpec] = {
    "python": GrammarSpec(
        def_types={"function_definition": "function", "class_definition": "class"},
        class_types={"class_definition"},
        call_types={"call"},
        import_types={"import_statement", "import_from_statement"},
        callee_field="function",
    ),
    "javascript": GrammarSpec(
        def_types={
            "function_declaration": "function",
            "generator_function_declaration": "function",
            "method_definition": "method",
            "class_declaration": "class",
        },
        class_types={"class_declaration"},
        call_types={"call_expression", "new_expression"},
        import_types={"import_statement"},
        callee_field="function",
    ),
    "typescript": GrammarSpec(
        def_types={
            "function_declaration": "function",
            "method_definition": "method",
            "method_signature": "method",
            "class_declaration": "class",
            "interface_declaration": "interface",
            "abstract_class_declaration": "class",
        },
        class_types={"class_declaration", "abstract_class_declaration"},
        call_types={"call_expression", "new_expression"},
        import_types={"import_statement"},
        callee_field="function",
    ),
    "go": GrammarSpec(
        def_types={
            "function_declaration": "function",
            "method_declaration": "method",
            "type_declaration": "class",
        },
        class_types={"type_declaration"},
        call_types={"call_expression"},
        import_types={"import_declaration", "import_spec"},
        callee_field="function",
    ),
    "java": GrammarSpec(
        def_types={
            "method_declaration": "method",
            "constructor_declaration": "method",
            "class_declaration": "class",
            "interface_declaration": "interface",
            "enum_declaration": "class",
        },
        class_types={"class_declaration", "interface_declaration", "enum_declaration"},
        call_types={"method_invocation", "object_creation_expression"},
        import_types={"import_declaration"},
        callee_field="name",
    ),
    "rust": GrammarSpec(
        def_types={
            "function_item": "function",
            "struct_item": "class",
            "trait_item": "interface",
            "enum_item": "class",
            "impl_item": "class",
        },
        class_types={"struct_item", "trait_item", "enum_item"},
        call_types={"call_expression", "macro_invocation"},
        import_types={"use_declaration"},
        callee_field="function",
    ),
    "ruby": GrammarSpec(
        def_types={"method": "method", "class": "class", "module": "class"},
        class_types={"class", "module"},
        call_types={"call", "method_call"},
        import_types={"call"},  # require statements look like calls; handled loosely
        callee_field="method",
    ),
}

# tsx reuses the typescript spec.
GRAMMARS["tsx"] = GRAMMARS["typescript"]


def get_grammar_spec(grammar: str) -> GrammarSpec | None:
    return GRAMMARS.get(grammar)
