"""Every relative link in a public doc resolves, and an anchor names a heading. A path in tests/public_docs.NOT_YET may
dangle until the task that writes it."""
from tests.public_docs import NOT_YET, ROOT, heading_slugs, links, public_docs


def test_every_relative_link_resolves():
    bad = []
    for doc in public_docs():
        for n, target in links(doc):
            path, _, anchor = target.partition("#")
            dest = (doc.parent / path).resolve() if path else doc
            rel = dest.relative_to(ROOT).as_posix() if dest.is_relative_to(ROOT) else str(dest)
            if rel in NOT_YET:
                continue
            where = f"{doc.relative_to(ROOT)}:{n}: {target}"
            if not dest.exists():
                bad.append(f"{where} doesn't exist")
            elif anchor and dest.suffix == ".md" and anchor not in heading_slugs(dest):
                bad.append(f"{where} names no heading there")
    assert bad == []


def test_nothing_waits_that_already_exists():
    assert sorted(p for p in NOT_YET if (ROOT / p).exists()) == [], "take these off NOT_YET in tests/public_docs.py"
