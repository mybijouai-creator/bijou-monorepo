"""
2026-08-22: login.html had a stray extra `}` (packages/backend/static/login.html,
introduced by commit 6973a92) that made the entire inline <script> block fail to
parse in the browser. Because CI's "Node syntax check (.cjs)" step only globs
*.cjs files, this was invisible to CI — the JS silently never ran, so the login
form's submit handler, the Google button, and the forgot-password wiring never
registered. The backend API itself was fine; the page was just dead. This is
exactly the "backend 200, UI broken" gap a Python test suite can't see.

This test extracts every inline, plain-JS (non-`src=`, non-`text/babel`)
<script> block from every static/*.html page and runs `node --check` on it,
so a syntax error anywhere fails CI instead of shipping silently.
`type="text/babel"` blocks (dashboard.html's JSX, transpiled client-side by
Babel standalone) are skipped — plain `node --check` can't parse JSX and
validating those would need @babel/core, out of scope for this check.
"""

import re
import subprocess
from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
SCRIPT_RE = re.compile(
    r'<script(?![^>]*\bsrc=)(?![^>]*type="text/babel")[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _html_files():
    return sorted(STATIC_DIR.glob("*.html"))


@pytest.mark.parametrize("html_path", _html_files(), ids=lambda p: p.name)
def test_inline_scripts_parse(html_path, tmp_path):
    text = html_path.read_text(encoding="utf-8")
    blocks = SCRIPT_RE.findall(text)
    for i, block in enumerate(blocks):
        if not block.strip():
            continue
        js_file = tmp_path / f"{html_path.stem}_{i}.js"
        js_file.write_text(block, encoding="utf-8")
        result = subprocess.run(
            ["node", "--check", str(js_file)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"{html_path.name} inline <script> block #{i} fails to parse:\n{result.stderr}"
        )
