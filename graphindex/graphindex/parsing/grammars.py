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
        def_types={"method": "method", "class": "class", "module": "class", "singleton_method": "method"},
        class_types={"class", "module"},
        call_types={"call", "method_call"},
        import_types={"call"},  # require statements look like calls; handled loosely
        callee_field="method",
    ),
    "c": GrammarSpec(
        def_types={"function_definition": "function", "struct_specifier": "class", "enum_specifier": "class"},
        class_types={"struct_specifier", "enum_specifier"},
        call_types={"call_expression"},
        import_types={"preproc_include"},
    ),
    "cpp": GrammarSpec(
        def_types={
            "function_definition": "function",
            "class_specifier": "class",
            "struct_specifier": "class",
            "enum_specifier": "class",
            "namespace_definition": "module",
        },
        class_types={"class_specifier", "struct_specifier", "enum_specifier"},
        call_types={"call_expression"},
        import_types={"preproc_include"},
    ),
    "c_sharp": GrammarSpec(
        def_types={
            "method_declaration": "method",
            "class_declaration": "class",
            "interface_declaration": "interface",
            "struct_declaration": "class",
            "enum_declaration": "class",
            "namespace_declaration": "module",
        },
        class_types={"class_declaration", "interface_declaration", "struct_declaration"},
        call_types={"invocation_expression", "object_creation_expression"},
        import_types={"using_directive"},
        name_field="name",
    ),
    "php": GrammarSpec(
        def_types={
            "function_definition": "function",
            "method_declaration": "method",
            "class_declaration": "class",
            "interface_declaration": "interface",
            "trait_declaration": "interface",
        },
        class_types={"class_declaration", "interface_declaration", "trait_declaration"},
        call_types={"function_call_expression", "member_call_expression", "object_creation_expression"},
        import_types={"include_expression", "require_expression", "namespace_use_declaration"},
        name_field="name",
    ),
    "zig": GrammarSpec(
        def_types={
            "function_declaration": "function",
            "variable_declaration": "class",
        },
        class_types={"variable_declaration"},
        call_types={"call_expression"},
    ),
    "kotlin": GrammarSpec(
        def_types={
            "function_declaration": "function",
            "class_declaration": "class",
            "object_declaration": "class",
            "interface_declaration": "interface",
        },
        class_types={"class_declaration", "object_declaration", "interface_declaration"},
        call_types={"call_expression"},
        import_types={"import_header"},
    ),
    "bash": GrammarSpec(
        def_types={"function_definition": "function"},
        call_types={"command"},
    ),
    "dart": GrammarSpec(
        def_types={
            "function_signature": "function",
            "class_definition": "class",
            "enum_declaration": "class",
        },
        class_types={"class_definition", "enum_declaration"},
        call_types={"call_expression"},
        import_types={"import_directive"},
    ),
    "lua": GrammarSpec(
        def_types={"function_definition": "function", "local_function_definition": "function"},
        call_types={"function_call"},
    ),
    "sql": GrammarSpec(
        def_types={"create_table_statement": "class", "create_view_statement": "class", "create_function_statement": "function"},
        class_types={"create_table_statement", "create_view_statement"},
    ),
}

# tsx reuses the typescript spec.
GRAMMARS["tsx"] = GRAMMARS["typescript"]


def get_grammar_spec(grammar: str) -> GrammarSpec | None:
    return GRAMMARS.get(grammar)
