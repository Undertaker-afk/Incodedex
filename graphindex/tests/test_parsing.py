from graphindex.parsing.symbols import extract_symbols


def test_python_symbols_calls_inheritance_imports():
    src = b"""import os
from pkg.models import Dog

class Animal:
    def speak(self):
        return noise()

class Dog(Animal):
    def speak(self):
        return bark()

def bark():
    return 'woof'
"""
    pf = extract_symbols("python", src)
    names = {s.name for s in pf.symbols}
    assert {"Animal", "Dog", "bark"} <= names
    dog = next(s for s in pf.symbols if s.name == "Dog")
    assert "Animal" in dog.bases
    speak = next(s for s in pf.symbols if s.qualified_name == "Dog.speak")
    assert speak.kind == "method"
    assert "bark" in speak.calls
    mods = {m for imp in pf.imports for m in imp.modules}
    assert "os" in mods and "pkg.models" in mods
    assert "Dog" not in mods  # imported names are not modules


def test_javascript_class_extends():
    src = b"""class Base {}
class Widget extends Base { render() { return draw(1); } }
function draw(x){ return x; }
"""
    pf = extract_symbols("javascript", src)
    widget = next(s for s in pf.symbols if s.name == "Widget")
    assert "Base" in widget.bases


def test_unknown_grammar_is_graceful():
    pf = extract_symbols("nonexistent", b"whatever")
    assert pf.ok is False
    assert pf.symbols == []
