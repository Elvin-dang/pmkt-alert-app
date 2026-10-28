"""Runs the Deno tests of the Supabase function supabase/functions/pmkt-admin (needs npx; Deno is fetched by npx)."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.skipif(shutil.which("npx") is None or sys.platform == "win32", reason="needs npx (Node)")
def test_pmkt_admin_function():
    r = subprocess.run(["npx", "--yes", "deno", "test", "--no-prompt", "supabase/functions/pmkt-admin/"],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
