import subprocess
import sys


def test_engine_imports_no_database_or_web_modules():
    code = (
        "import sys\n"
        "import steward.engine, steward.engine.datafiles\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('sqlalchemy', 'fastapi', 'httpx2', 'alembic')"
        " or m.startswith(('steward.db', 'steward.api', 'steward.settings', 'steward.app')))\n"
        "print(bad)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]", f"engine pulled in forbidden modules: {out}"
