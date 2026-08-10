#!/usr/bin/env node
// PreToolUse guard for Bash commands in the Bijou monorepo.
//
// Why this exists: the working tree carries ~82 untracked scratch files
// (ops/_*.js probes, *.err logs, test PNGs) alongside raw deploy credentials
// written by ops scripts (ops/.fly_token = fm2_..., ops/.vercel_token = vcp_...).
// A single `git add -A` sweeps all of it into a commit. That has already
// happened once here — hence ops/ holding 49 tracked `_*` scratch files and a
// commit literally named "resolve merge conflict after secret scrub".
//
// Node is used rather than a shell script because it behaves identically under
// PowerShell and Git Bash on Windows.
//
// Contract: exit 0 allows, exit 2 blocks and shows stderr to Claude.

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let cmd = "";
  try {
    cmd = JSON.parse(raw)?.tool_input?.command ?? "";
  } catch {
    process.exit(0); // Unparseable payload: never block on our own bug.
  }

  // `git add -A`, `git add .`, `git add --all`, `git commit -a`.
  // Deliberately narrow: explicit pathspecs stay allowed.
  const bulkAdd =
    /\bgit\s+add\s+(-A\b|--all\b|\.(?:\s|$))/.test(cmd) ||
    /\bgit\s+commit\b[^|;]*\s-[a-zA-Z]*a/.test(cmd);

  if (bulkAdd) {
    console.error(
      [
        "BLOCKED: bulk `git add` in a tree with untracked credentials.",
        "",
        "ops/.fly_token (fm2_...) and ops/.vercel_token (vcp_...) are live deploy",
        "credentials, and ~82 untracked scratch files sit beside them.",
        "",
        "Stage explicit paths instead:",
        "  git add packages/backend/src/saas/auth_api.py",
        "",
        "Then confirm nothing unintended is staged:",
        "  git diff --cached --name-only",
      ].join("\n"),
    );
    process.exit(2);
  }

  process.exit(0);
});
