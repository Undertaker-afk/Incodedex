from pkg.models import Dog, Cat

def make_dog():
    d = Dog()
    return d.speak()

def make_cat():
    c = Cat()
    return c.speak()

def unused_helper(x):
    # dead code: never referenced
    return x * 2

def duplicate_a(items):
    total = 0
    for it in items:
        total += it
    return total

def duplicate_b(items):
    total = 0
    for it in items:
        total += it
    return total
