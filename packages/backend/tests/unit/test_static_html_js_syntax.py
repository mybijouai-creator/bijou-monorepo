"""
2026-08-22: login.html had a stray extra `}` (packages/backend/static/login.html,
introduced by commit 6973a92) that made the entire inline <script> block fail to
parse in the browser. Because CI's "Node syntax check (.cjs)" step only globs
*.cjs files, this was invisible to CI — the JS silently never ran, so the login
form's submit handler, the Google button, and the forgot-password wiring never
registered. The backend API itself was fine; the page was just dead. This is
exactly the "backend 200, UI broken" gap a Python test suite can't see.

This test extracts every inline, plain-JS (non-`src=`) <script> block from
every static/*.html page and runs `node --check` on it, so a syntax error
anywhere fails CI instead of shipping silently.

`type="text/babel"` blocks (dashboard.html's JSX, transpiled client-side by
Babel standalone) get a separate check: plain `node --check` can't parse
JSX, but `@babel/parser` (declared as a packages/backend devDependency —
CI's existing "Node deps" step installs it there, working-directory:
packages/backend — a copy that happened to be present at the monorepo root
only as an incidental transitive dep of the landing package would NOT be
guaranteed in CI) can parse-only (no transform, no preset needed) — so
those blocks are validated with that instead of skipped.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = BACKEND_DIR / "static"
REPO_ROOT = BACKEND_DIR.parents[1]
# Prefer packages/backend's own node_modules (reliable — CI installs it via
# package.json there); fall back to the monorepo root's (works locally even
# before `npm install` has been run inside packages/backend).
BABEL_CWD = BACKEND_DIR if (BACKEND_DIR / "node_modules" / "@babel" / "parser").exists() else REPO_ROOT

PLAIN_SCRIPT_RE = re.compile(
    r'<script(?![^>]*\bsrc=)(?![^>]*type="text/babel")[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
BABEL_SCRIPT_RE = re.compile(
    r'<script type="text/babel"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _html_files():
    return sorted(STATIC_DIR.glob("*.html"))


def _check_plain_js(block, js_file):
    js_file.write_text(block, encoding="utf-8")
    result = subprocess.run(["node", "--check", str(js_file)], capture_output=True, text=True)
    return result.returncode == 0, result.stderr


def _check_jsx(block, js_file):
    js_file.write_text(block, encoding="utf-8")
    script = (
        "const fs=require('fs');"
        "const parser=require('@babel/parser');"
        f"const src=fs.readFileSync({json.dumps(str(js_file))},'utf8');"
        "try{parser.parse(src,{sourceType:'module',plugins:['jsx']});"
        "console.log('OK');}"
        "catch(e){console.log('FAIL:'+e.message);process.exit(1);}"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, cwd=str(BABEL_CWD)
    )
    return result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("html_path", _html_files(), ids=lambda p: p.name)
def test_inline_scripts_parse(html_path, tmp_path):
    text = html_path.read_text(encoding="utf-8")

    for i, block in enumerate(PLAIN_SCRIPT_RE.findall(text)):
        if not block.strip():
            continue
        js_file = tmp_path / f"{html_path.stem}_plain_{i}.js"
        ok, err = _check_plain_js(block, js_file)
        assert ok, f"{html_path.name} inline <script> block #{i} fails to parse:\n{err}"

    for i, block in enumerate(BABEL_SCRIPT_RE.findall(text)):
        if not block.strip():
            continue
        jsx_file = tmp_path / f"{html_path.stem}_babel_{i}.jsx"
        ok, err = _check_jsx(block, jsx_file)
        assert ok, f"{html_path.name} text/babel <script> block #{i} fails to parse:\n{err}"
