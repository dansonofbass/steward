"""Find regular expressions whose running time can grow faster than their input (SEC-3's class).

Python's `re` backtracks, and one call runs inside the engine holding the interpreter lock, so a pattern that is
quadratic in its input freezes the whole server for an upload under the size cap. Two shapes cause it:

- **span**: an open-ended repeat (`.*?`, `[^x]+`, `\\s*`) that can run over the place where the pattern could
  start again, followed by something that can fail. With no match, every start scans to the end of the run, so
  the time is the square of the input. `<STMTTRN>(.*?)</STMTTRN>` on many opening tags and no closing tag is it.
  Not when the way to the repeat needs a character the repeat never steps over (`<X>([^<]*)</X>`).
- **nested**: an open-ended repeat inside another whose turns can trade characters (`(a+)+`), which can be
  exponential. Not when another required part of each turn takes characters the inner repeat can't
  (`(?:[.][a-z]+)+`), and not when nothing after it can fail.

A pattern that can only start in one place (`\\A`, `^` without MULTILINE, or used only with `.match` and
`.fullmatch`, itself or as each item of a list the module loops over) has no span problem. Patterns are read from the source; one built when its module is imported is
read from the module. One built inside a function can't be judged and is reported as `dynamic`. Character sets
are tested over every byte and a few wider code points, which is exact enough for these shapes. Lookbehinds don't
count, so a pattern they keep linear is reported and needs a listed reason.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from re import _constants as C  # noqa: PLC2701 - the parser is the only exact reading of a pattern
from re import _parser as P  # noqa: PLC2701

_REPEATS = {C.MAX_REPEAT, C.MIN_REPEAT, C.POSSESSIVE_REPEAT}
_CHAR_OPS = {C.LITERAL, C.NOT_LITERAL, C.ANY, C.IN}
# Every byte, plus code points where case folding or "any character" differs from ASCII.
_ALL = frozenset([*range(256), 0x130, 0x131, 0x17F, 0x212A, 0x2028, 0x3000, 0x4E00])
_CATEGORIES = {getattr(C, f"CATEGORY_{n}"): re.compile(rx) for n, rx in (
    ("DIGIT", r"\d"), ("NOT_DIGIT", r"\D"), ("SPACE", r"\s"), ("NOT_SPACE", r"\S"), ("WORD", r"\w"),
    ("NOT_WORD", r"\W"), ("LINEBREAK", r"\n"), ("NOT_LINEBREAK", r"[^\n]"))}
_CALLS = {"compile": 1, "search": 2, "match": 2, "fullmatch": 2, "findall": 2, "finditer": 2, "split": 3, "sub": 4,
          "subn": 4}
_ONE_START = {"match", "fullmatch"}


def _fold(chars: set[int]) -> set[int]:
    out = set(chars)
    for c in chars:
        for v in (chr(c).lower(), chr(c).upper()):
            if len(v) == 1:
                out.add(ord(v))
    return out


def _chars(op, av, flags: int) -> frozenset[int]:
    if op is C.LITERAL:
        s = {av}
    elif op is C.NOT_LITERAL:
        s = set(_ALL - _fold({av})) if flags & re.I else set(_ALL - {av})
        return frozenset(s)
    elif op is C.ANY:
        return _ALL if flags & re.S else _ALL - {10}
    else:  # IN
        s, neg = set(), False
        for o, a in av:
            if o is C.NEGATE:
                neg = True
            elif o is C.LITERAL:
                s.add(a)
            elif o is C.RANGE:
                s.update(c for c in _ALL if a[0] <= c <= a[1])
            elif o is C.CATEGORY:
                s.update(c for c in _ALL if _CATEGORIES[a].match(chr(c)))
        if flags & re.I:
            s = _fold(s)
        return frozenset(_ALL - s if neg else s)
    return frozenset(_fold(s) if flags & re.I else s)


def _sub_flags(av, flags: int) -> int:
    _group, add, drop, _p = av
    return (flags | add) & ~drop


def _first(seq, flags: int) -> tuple[set[int], bool]:
    """The characters a match of `seq` can begin with, and whether `seq` can match nothing."""
    out: set[int] = set()
    for op, av in seq:
        if op in _CHAR_OPS:
            return out | _chars(op, av, flags), False
        if op in _REPEATS:
            f, empty = _first(av[2], flags)
            out |= f
            if av[0] > 0 and not empty:
                return out, False
        elif op is C.SUBPATTERN:
            f, empty = _first(av[3], _sub_flags(av, flags))
            out |= f
            if not empty:
                return out, False
        elif op is C.ATOMIC_GROUP:
            f, empty = _first(av, flags)
            out |= f
            if not empty:
                return out, False
        elif op is C.BRANCH:
            firsts = [_first(alt, flags) for alt in av[1]]
            for f, _ in firsts:
                out |= f
            if not any(e for _, e in firsts):
                return out, False
        elif op is C.GROUPREF_EXISTS:
            for alt in av[1:]:
                if alt is not None:
                    out |= _first(alt, flags)[0]
            return out | _ALL, True
        elif op is C.GROUPREF:
            return out | _ALL, True
        # AT, ASSERT and ASSERT_NOT match nothing and the next item decides.
    return out, True


def _can_fail(seq, flags: int) -> bool:
    for op, av in seq:
        if op in _CHAR_OPS or op in (C.AT, C.ASSERT, C.ASSERT_NOT, C.GROUPREF, C.GROUPREF_EXISTS):
            return True
        if op in _REPEATS and av[0] > 0 and _can_fail(av[2], flags):
            return True
        if op is C.SUBPATTERN and _can_fail(av[3], _sub_flags(av, flags)):
            return True
        if op is C.ATOMIC_GROUP and _can_fail(av, flags):
            return True
        if op is C.BRANCH and all(_can_fail(alt, flags) for alt in av[1]):
            return True
    return False


def _run(seq, flags: int) -> set[int]:
    """Every character a repeat of `seq` can step over."""
    out: set[int] = set()
    for op, av in seq:
        if op in _CHAR_OPS:
            out |= _chars(op, av, flags)
        elif op in _REPEATS:
            out |= _run(av[2], flags)
        elif op is C.SUBPATTERN:
            out |= _run(av[3], _sub_flags(av, flags))
        elif op is C.ATOMIC_GROUP:
            out |= _run(av, flags)
        elif op is C.BRANCH:
            for alt in av[1]:
                out |= _run(alt, flags)
        elif op is C.GROUPREF_EXISTS:
            for alt in av[1:]:
                if alt is not None:
                    out |= _run(alt, flags)
        elif op is C.GROUPREF:
            out |= _ALL
    return out


def _anchored(seq, flags: int) -> bool:
    for op, av in seq:
        if op is C.AT:
            return av is C.AT_BEGINNING_STRING or (av is C.AT_BEGINNING and not flags & re.M)
        if op is C.SUBPATTERN:
            return _anchored(av[3], _sub_flags(av, flags))
        return False
    return False


def _children(op, av, flags: int) -> list:
    if op in _REPEATS:
        return [(av[2], flags)]
    if op is C.SUBPATTERN:
        return [(av[3], _sub_flags(av, flags))]
    if op is C.ATOMIC_GROUP:
        return [(av, flags)]
    if op is C.BRANCH:
        return [(alt, flags) for alt in av[1]]
    if op is C.GROUPREF_EXISTS:
        return [(alt, flags) for alt in av[1:] if alt is not None]
    if op in (C.ASSERT, C.ASSERT_NOT):
        return [(av[1], flags)]
    return []


def _backtracking_runs(op, av, flags: int) -> list[set[int]]:
    """What each open-ended, backtracking repeat in this item (itself included) can step over."""
    out = [_run(av[2], flags)] if op in (C.MAX_REPEAT, C.MIN_REPEAT) and av[1] == C.MAXREPEAT else []
    for seq, f in _children(op, av, flags):
        for o, a in seq:
            out += _backtracking_runs(o, a, f)
    return out


def _top_items(seq, flags: int) -> list:
    """A repeat body's items, looking through a lone group: [(op, av, flags)]."""
    while len(seq) == 1 and seq[0][0] in (C.SUBPATTERN, C.ATOMIC_GROUP):
        op, av = seq[0]
        seq, flags = (av[3], _sub_flags(av, flags)) if op is C.SUBPATTERN else (av, flags)
    return [(op, av, flags) for op, av in seq]


def _separates(op, av, flags: int, run: set[int]) -> bool:
    """A required item that takes characters `run` never can, so turns of the repeat around it can't trade them."""
    if op in (C.AT, C.ASSERT, C.ASSERT_NOT) or not _can_fail([(op, av)], flags):
        return False
    mine = _run([(op, av)], flags)
    return bool(mine) and not mine & run


def _ambiguous(body, flags: int) -> bool:
    """Can a repeat inside one turn of this body trade characters with the next turn (`(a+)+`)? Not when another
    required item of the body takes characters the inner repeat never can (the dot in `(?:[.][a-z]+)+`)."""
    items = _top_items(body, flags)
    for k, (op, av, f) in enumerate(items):
        for run in _backtracking_runs(op, av, f):
            if not any(j != k and _separates(o, a, g, run) for j, (o, a, g) in enumerate(items)):
                return True
    return False


def shapes(pattern: str | bytes, flags: int = 0, *, one_start: bool = False) -> set[str]:
    """The risky shapes in `pattern`: a subset of {"span", "nested"}."""
    tree = P.parse(pattern, flags)
    flags = tree.state.flags
    first, empty = _first(tree.data, flags)
    if empty:
        first = set(_ALL)
    many = not (one_start or _anchored(tree.data, flags))
    found: set[str] = set()

    def walk(seq, flags: int, tail_fails: bool, before: list) -> None:
        """`before`: the items a match passes on its way to `seq`, as (op, av, flags)."""
        for i, (op, av) in enumerate(seq):
            tail = tail_fails or _can_fail(seq[i + 1:], flags)
            if op in _REPEATS and av[1] == C.MAXREPEAT:
                run = _run(av[2], flags)
                # A later start can fall inside this repeat's run only if everything on the way here can match
                # inside it too: `app/[^/]*x` can't start again inside `[^/]*`, since its way there needs a `/`.
                inside = run & first and not any(_separates(o, a, f, run) for o, a, f in before)
                if many and tail and inside:
                    found.add("span")
                if op is not C.POSSESSIVE_REPEAT and tail and _ambiguous(av[2], flags):
                    found.add("nested")
            # After a repeat's body comes the repeat's own tail, or another turn the repeat still needs. Inside a
            # lookaround, only the lookaround's own end follows.
            more = op in _REPEATS and av[0] > 1 and _can_fail(av[2], flags)
            look = op in (C.ASSERT, C.ASSERT_NOT)
            for inner, f in _children(op, av, flags):
                walk(inner, f, False if look else tail or more, before)
            before = [*before, (op, av, flags)]

    walk(tree.data, flags, False, [])
    return found


@dataclass(frozen=True)
class Found:
    path: str
    line: int
    pattern: str
    shape: str  # "span", "nested" or "dynamic"


class _Unknown(Exception):
    pass


def _value(node: ast.AST, consts: dict[str, object]):
    """A literal pattern or flags value, or _Unknown. `re.escape(x)` inside an f-string reads as a plain letter."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes, int)):
        return node.value
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "re":
        flag = getattr(re, node.attr, None)
        if isinstance(flag, re.RegexFlag):
            return int(flag)
    if isinstance(node, ast.BinOp):
        left, right = _value(node.left, consts), _value(node.right, consts)
        if isinstance(node.op, ast.BitOr) and isinstance(left, int) and isinstance(right, int):
            return left | right
        if isinstance(node.op, ast.Add) and type(left) is type(right) and isinstance(left, (str, bytes)):
            return left + right
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                out.append(part.value)
            elif (isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Call)
                  and isinstance(part.value.func, ast.Attribute) and part.value.func.attr == "escape"):
                out.append("x")
            elif (isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name)
                  and isinstance(consts.get(part.value.id), str) and part.format_spec is None):
                out.append(consts[part.value.id])
            else:
                raise _Unknown
        return "".join(out)
    raise _Unknown


def _module_constants(tree: ast.Module) -> dict[str, object]:
    consts: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                consts[node.targets[0].id] = _value(node.value, consts)
            except _Unknown:
                pass
    return consts


def _match_only(tree: ast.Module) -> set[str]:
    """Names whose compiled pattern is only ever used as `NAME.match(...)` or `NAME.fullmatch(...)`, or, for a
    list of patterns, only looped over (`for rx in NAME`, or a comprehension) with each `rx` used only that way."""
    parent = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def matched(node: ast.AST) -> bool:
        up = parent.get(id(node))
        return isinstance(up, ast.Attribute) and up.value is node and up.attr in _ONE_START

    def each_matched(name: str, scope: list[ast.AST]) -> bool:
        loads = [n for s in scope for n in ast.walk(s)
                 if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)]
        return bool(loads) and all(matched(n) for n in loads)

    uses: dict[str, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            up = parent.get(id(node))
            one = matched(node)
            if isinstance(up, ast.comprehension) and up.iter is node and isinstance(up.target, ast.Name):
                owner = parent[id(up)]  # the ListComp, GeneratorExp, SetComp or DictComp
                scope = [c for c in ast.iter_child_nodes(owner) if c is not up]
                one = each_matched(up.target.id, scope + up.ifs)
            elif isinstance(up, ast.For) and up.iter is node and isinstance(up.target, ast.Name):
                one = each_matched(up.target.id, up.body)
            uses[node.id] = uses.get(node.id, True) and one
    return {n for n, one in uses.items() if one}


def _deferred(tree: ast.Module) -> set[int]:
    """ids of the nodes that run only when a function is called, not when the module is imported."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            out.update(id(n) for n in ast.walk(node) if n is not node)
    return out


def _held_patterns(value, depth: int = 3):
    """Compiled patterns in a module global, looking into dicts, lists, tuples and sets."""
    if isinstance(value, re.Pattern):
        yield value
    elif depth and isinstance(value, dict):
        for v in value.values():
            yield from _held_patterns(v, depth - 1)
    elif depth and isinstance(value, (list, tuple, set, frozenset)):
        for v in value:
            yield from _held_patterns(v, depth - 1)


def scan(path: Path, root: Path, module=None) -> list[Found]:
    """Every risky pattern in one source file. With its imported `module`, a pattern built at import time is read
    from the module's globals instead of being reported as dynamic."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    consts = _module_constants(tree)
    match_only = _match_only(tree)
    deferred = _deferred(tree)
    targets: dict[int, str] = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)):
            targets[id(node.value)] = node.targets[0].id
    out: list[Found] = []
    read: set[tuple[str | bytes, int]] = set()
    rel = path.relative_to(root).as_posix()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "re"
                and node.func.attr in _CALLS and node.args):
            continue
        name = node.func.attr
        flags_node = next((k.value for k in node.keywords if k.arg == "flags"), None)
        if flags_node is None and len(node.args) > _CALLS[name]:
            flags_node = node.args[_CALLS[name]]
        try:
            pattern = _value(node.args[0], consts)
            flags = 0 if flags_node is None else _value(flags_node, consts)
            if not isinstance(pattern, (str, bytes)) or not isinstance(flags, int):
                raise _Unknown
        except _Unknown:
            if module is None or id(node) in deferred:
                out.append(Found(rel, node.lineno, ast.unparse(node.args[0]), "dynamic"))
            continue
        read.add((pattern, flags))
        one = name in _ONE_START or (name == "compile" and targets.get(id(node)) in match_only)
        for shape in sorted(shapes(pattern, flags, one_start=one)):
            out.append(Found(rel, node.lineno, pattern if isinstance(pattern, str) else repr(pattern), shape))
    if module is not None:
        own = {t.id for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
               for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
               for t in ast.walk(t) if isinstance(t, ast.Name)}  # not the patterns it imports
        for gname, value in vars(module).items():
            if gname not in own:
                continue
            for rx in _held_patterns(value):
                # Literal patterns were read above, with their flags as written. Here rx.flags carries re.UNICODE.
                if any(rx.pattern == p and (rx.flags & ~re.U) == (f & ~re.U) for p, f in read):
                    continue
                for shape in sorted(shapes(rx.pattern, rx.flags, one_start=gname in match_only)):
                    text = rx.pattern if isinstance(rx.pattern, str) else repr(rx.pattern)
                    out.append(Found(rel, 0, text, shape))
    return out
