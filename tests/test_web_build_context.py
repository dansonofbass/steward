"""The Docker web stage copies only web/, so nothing under web/src may import a path that resolves outside web/."""
import re
from pathlib import Path

WEB = Path(__file__).parents[1] / "web"
SPEC = re.compile(r"""(?:from|import|require)\s*\(?\s*['"](\.{1,2}/[^'"]*)['"]""")


def test_web_src_imports_stay_inside_web():
    escaped = []
    for f in sorted((WEB / "src").rglob("*")):
        if f.suffix not in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".css"} or not f.is_file():
            continue
        for m in SPEC.finditer(f.read_text()):
            spec = m.group(1)
            target = (f.parent / spec).resolve()
            if not target.is_relative_to(WEB.resolve()):
                escaped.append(f"{f.relative_to(WEB.parent)} -> {spec}")
    assert not escaped, "web/src imports outside web/ (not in the Docker build context):\n" + "\n".join(escaped)
