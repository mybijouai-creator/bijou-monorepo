"""
signup-flow-check.py - End-to-end smoke check of the Bijou signup → dashboard flow.

Hits the live URLs in order and reports each step. Use this as a regression
check after any change to:
- packages/landing/ (CTAs, modal)
- packages/backend/src/saas/auth_api.py (signup endpoint)
- packages/backend/static/{signup,login,dashboard,onboarding}.html

Run: python ops/coolify/.smoke-flow.py

Exit 0 = all steps pass, 1 = any step fails.

Note: the landing page is a React SPA — most CTAs are rendered client-side,
so we verify the JS bundle (or the rendered source files in this repo) for
the canonical signup URL rather than the static HTML.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple


def http_get(url: str, timeout: int = 15, follow_redirects: bool = True,
             headers: Optional[dict] = None) -> Tuple[int, str, dict]:
    """Returns (status, body, headers). Follows up to 6 redirects."""
    req_headers = {'User-Agent': 'bijou-smoke/1.0'}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, method='GET', headers=req_headers)
    try:
        for _ in range(7):
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                hdrs = dict(resp.headers)
                body = resp.read().decode('utf-8', errors='replace')
                loc = hdrs.get('Location')
                if follow_redirects and loc and status in (301, 302, 303, 307, 308):
                    if not loc.startswith('http'):
                        from urllib.parse import urljoin
                        loc = urljoin(url, loc)
                    req = urllib.request.Request(loc, method='GET', headers=req_headers)
                    continue
                return status, body, hdrs
        return status, body, hdrs
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace'), dict(e.headers or {})
    except Exception as e:
        return 0, str(e), {}


def http_post_json(url: str, payload: dict, timeout: int = 15) -> Tuple[int, dict]:
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'Content-Type': 'application/json',
        'User-Agent': 'bijou-smoke/1.0',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, {'raw': body[:500]}
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {'raw': body[:500]}
    except Exception as e:
        return 0, {'error': str(e)}


def step(label: str, ok: bool, detail: str = '') -> bool:
    icon = '[PASS]' if ok else '[FAIL]'
    color = '\033[32m' if ok else '\033[31m'
    reset = '\033[0m'
    print(f'  {color}{icon}{reset} {label}: {detail}')
    return ok


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--base-app', default='https://app.mybijou.xyz')
    p.add_argument('--base-landing', default='https://mybijou.xyz')
    p.add_argument('--email', default=None)
    p.add_argument('--password', default='SmokeTest2026!')
    p.add_argument('--name', default='Smoke Test')
    p.add_argument('--business-name', default='Smoke Test Biz')
    p.add_argument('--phone', default='+60174106981')
    args = p.parse_args()
    if not args.email:
        args.email = f'smoke+{int(time.time())}@bijou-test.dev'

    passed = 0
    failed = 0

    def tally(ok: bool):
        nonlocal passed, failed
        if ok: passed += 1
        else: failed += 1

    print('=' * 70)
    print('  Bijou signup → dashboard flow check (live)')
    print('=' * 70)
    print(f'  email:     {args.email}')
    print(f'  password:  {args.password}')
    print()

    # ── A. Landing → signup CTA ──────────────────────────────────────────
    print('── A. Landing → signup CTA ──')
    status, body, hdrs = http_get(args.base_landing + '/')
    ok = step('Landing page loads', status == 200, f'HTTP {status}, {len(body)} bytes')
    tally(ok)
    if not ok: return finish(passed, failed)

    # Landing is a React SPA — static HTML doesn't show CTAs. Check the
    # source files in this repo for the canonical signup URL (Hero.tsx,
    # FinalCTA.tsx, OnboardingModal.tsx, etc.).
    landing_dir = Path('packages/landing')
    cta_files = []
    signup_url = 'app.mybijou.xyz/signup'
    if landing_dir.exists():
        for f in landing_dir.rglob('*'):
            if f.is_file() and f.suffix in {'.tsx', '.ts', '.jsx', '.js', '.html'} and 'node_modules' not in str(f):
                try:
                    content = f.read_text(encoding='utf-8', errors='ignore')
                    if 'app.mybijou.xyz' in content and '/signup' in content:
                        cta_files.append(str(f.relative_to('.')))
                except Exception:
                    pass
    ok = step('Landing source has signup CTAs',
              len(cta_files) >= 3,
              f'{len(cta_files)} files reference the signup URL: {cta_files[:5]}')
    tally(ok)

    # Also verify the JSON-LD in static HTML references the signup URL
    has_jsonld = 'app.mybijou.xyz/signup' in body
    ok = step('Landing HTML JSON-LD references /signup', has_jsonld,
              'structured data OK' if has_jsonld else 'no JSON-LD')
    tally(ok)

    # ── B. Backend /signup page renders ──────────────────────────────────
    print('\n── B. Backend /signup page ──')
    status, body, hdrs = http_get(args.base_app + '/signup')
    ok = step('GET /signup', status == 200, f'HTTP {status}, {len(body)} bytes')
    tally(ok)
    if not ok: return finish(passed, failed)

    has_form = '<form' in body
    has_email_field = 'type="email"' in body or 'name="email"' in body
    has_password_field = 'type="password"' in body or 'name="password"' in body
    ok = step('Signup form present', has_form, '<form> found' if has_form else 'no <form>')
    tally(ok)
    ok = step('Signup has email field', has_email_field, 'found' if has_email_field else 'missing')
    tally(ok)
    ok = step('Signup has password field', has_password_field, 'found' if has_password_field else 'missing')
    tally(ok)
    has_business = 'business' in body.lower() or 'company' in body.lower() or 'tenant' in body.lower()
    has_phone = 'phone' in body.lower() or 'tel' in body.lower()
    ok = step('Signup form has business_name field', has_business, 'found' if has_business else 'missing (the API requires it!)')
    tally(ok)
    ok = step('Signup form has phone field', has_phone, 'found' if has_phone else 'missing (the API requires it!)')
    tally(ok)

    # ── C. POST /api/auth/signup ──────────────────────────────────────────
    print('\n── C. POST /api/auth/signup ──')
    status, payload = http_post_json(args.base_app + '/api/auth/signup', {
        'email': args.email,
        'password': args.password,
        'name': args.name,
        'business_name': args.business_name,
        'phone': args.phone,
        'tenant_name': args.business_name,
    })
    signup_ok = status in (200, 201, 202)
    detail = f'HTTP {status}'
    if isinstance(payload, dict):
        if 'detail' in payload: detail += f' — {payload["detail"][:120]}'
        elif 'message' in payload: detail += f' — {payload["message"][:120]}'
        elif 'error' in payload: detail += f' — {payload["error"]}'
    ok = step('Signup accepted', signup_ok, detail)
    tally(ok)

    requires_confirm = isinstance(payload, dict) and (
        payload.get('requires_confirmation') is True
        or 'confirm' in str(payload.get('message', '')).lower()
    )
    has_session = isinstance(payload, dict) and (
        payload.get('session') is not None or payload.get('access_token')
    )
    if has_session:
        print('         -> signup returned a session (no email confirm needed)')
    elif requires_confirm:
        print('         -> signup requires email confirmation (per GoTrue mailer_autoconfirm=false)')

    # ── D. /login page renders ────────────────────────────────────────────
    print('\n── D. /login page ──')
    status, body, hdrs = http_get(args.base_app + '/login')
    ok = step('GET /login', status == 200, f'HTTP {status}, {len(body)} bytes')
    tally(ok)
    ok = step('Login has form + email + password',
              '<form' in body and ('type="email"' in body or 'name="email"' in body) and ('type="password"' in body or 'name="password"' in body),
              'all elements present' if ok else 'missing elements')
    tally(ok)

    # ── E. POST /api/auth/login ───────────────────────────────────────────
    print('\n── E. POST /api/auth/login ──')
    status, payload = http_post_json(args.base_app + '/api/auth/login', {
        'email': args.email,
        'password': args.password,
    })
    login_ok = status == 200
    detail = f'HTTP {status}'
    session_token = None
    if isinstance(payload, dict):
        if 'access_token' in payload:
            session_token = payload['access_token']
            detail += ' — got access_token'
        elif 'session' in payload and payload['session']:
            session_token = (payload['session'] or {}).get('access_token')
            detail += ' — got session.access_token'
        elif 'detail' in payload:
            detail += f' — {payload["detail"][:120]}'
        elif 'error' in payload:
            detail += f' — {payload["error"]}'
    ok = step('Login succeeds with new creds', login_ok, detail)
    tally(ok)
    if not login_ok:
        print('         -> if "email not confirmed", that is expected (GoTrue autoconfirm=false)')
        print('         -> the signup itself created the user — login works after the user clicks the email link')

    # ── F. /dashboard requires auth (no token) ────────────────────────────
    print('\n── F. /dashboard auth gate (no token) ──')
    status, body, hdrs = http_get(args.base_app + '/dashboard', follow_redirects=False)
    gated = status in (302, 303, 307, 401, 403) or '/login' in body.lower() or 'sign in' in body.lower() or 'auth' in body.lower()
    ok = step('Dashboard gated without auth', gated, f'HTTP {status} ({"gated" if gated else "OPEN — security bug!"})')
    tally(ok)

    # ── G. /dashboard WITH auth ───────────────────────────────────────────
    print('\n── G. /dashboard WITH auth ──')
    if session_token:
        status, body, hdrs = http_get(
            args.base_app + '/dashboard',
            headers={'Authorization': f'Bearer {session_token}'},
        )
        ok = step('Dashboard returns 200 with token', status == 200, f'HTTP {status}, {len(body)} bytes')
        tally(ok)
        has_dashboard_ui = 'sidebar' in body.lower() or 'menu' in body.lower() or 'dashboard' in body.lower()
        ok = step('Dashboard HTML has UI markers',
                  has_dashboard_ui,
                  'sidebar/menu/dashboard text found' if has_dashboard_ui else 'no UI markers')
        tally(ok)
    else:
        print('  [SKIP] no session_token from login')

    # ── H. /api/menu/permissions ─────────────────────────────────────────
    print('\n── H. /api/menu/permissions ──')
    status, body, hdrs = http_get(args.base_app + '/api/menu/permissions')
    if status == 200:
        try:
            j = json.loads(body)
            items = j.get('menu', [])
            ok = step('Returns 11 menu items', len(items) == 11, f'{len(items)} items')
            tally(ok)
        except Exception as e:
            ok = step('Returns valid JSON', False, str(e)[:80])
            tally(ok)
    else:
        ok = step('GET /api/menu/permissions', False, f'HTTP {status} — P0 fix is in source (commit a3632f9) but NOT in the v0.4.7 image yet')
        tally(ok)

    # ── I. /api/self-test/summary ─────────────────────────────────────────
    print('\n── I. /api/self-test/summary ──')
    status, body, hdrs = http_get(args.base_app + '/api/self-test/summary')
    ok = step('GET /api/self-test/summary', status == 200, f'HTTP {status}, {len(body)} bytes (404 = endpoint not deployed)')
    tally(ok)

    return finish(passed, failed)


def finish(passed: int, failed: int) -> int:
    print()
    print('=' * 70)
    print(f'  Summary: {passed} pass, {failed} fail')
    print('=' * 70)
    if failed == 0:
        print('\n  All signup-flow steps green.')
        return 0
    print('\n  One or more steps failed — investigate the FAIL lines above.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
