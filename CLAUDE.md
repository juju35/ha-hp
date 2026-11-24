# Repository guide for agents

## Commits
- Write every commit message in **English**, following **Conventional Commits**:
  `type(scope): subject` — types: `feat`, `fix`, `chore`, `docs`, `style`, `refactor`,
  `perf`, `test`, `build`, `ci`, `revert`. Subject in imperative mood, lower case,
  no trailing period, ≤ 72 chars.
- Author identity must be **juju35** (`juju35 <julienstephan29@gmail.com>`), never an assistant identity.
- Messages are checked by **commitlint** (Conventional Commits) via the pre-commit
  `commit-msg` hook; run `pre-commit install` once so the hook is active locally.
- **External contributions**: add the contributor as a commit **co-author** (their GitHub
  noreply address) **only** when they supplied a patch/PR or a translation — never for a
  mere idea or feature issue.
- Keep history clean and linear: small, focused commits, one logical change each.
- `main` is protected by a ruleset: **squash-merge only**, the commit message is the PR
  **title + description** (not the commit list, so the screenshots bot's `[skip ci]` never
  reaches `main`); tags follow a `v*` ruleset.

## Before opening a PR — run the checks locally
CI mirrors these; running them first avoids round-trips:
```sh
pre-commit run -a
vulture custom_components .vulture_whitelist.py --min-confidence 60
npx --yes jscpd@5.4.2 .
pytest
```

## Releasing — how it works here
A release follows **every `feat` or `fix` merge** on `main` (the squash title) whose version has no
tag yet; `ci`/`docs`/`test`/`chore`/`refactor` merges publish nothing. Other bumps (e.g. `perf`) wait
for the next feat/fix, or run the Release workflow by hand (`gh workflow run release.yml`). The notes
gather the CHANGELOG sections of every version since the previous tag.
**Never create a tag by hand.**

The `Version consistency` check (validate.yml) requires the **same version in every place**,
or the release fails.

## Bumping the version
This is an **INTEGRATION** repo. A bump is complete only when **every** file below
carries the new version, updated together in one commit:
1. `CHANGELOG.md` → add a "## X.Y.Z - YYYY-MM-DD" section at the top (`### Features` | `Fixes` | `Performance` | `Maintenance`).
2. `custom_components/hp/manifest.json` → `"version": "X.Y.Z"`.
3. `custom_components/hp/const.py` → `VERSION: Final = "X.Y.Z"`.
- Bump rule: `fix` → patch, `feat` → minor, breaking change → major.
- **Bump only when what users install changes** (shipped code, translations, assets of the
  release). CI, workflows, tests, screenshots, README, lint config, CLAUDE.md: no bump, no
  CHANGELOG entry, no version in the title (e.g. `ci: …`, `docs: …`, `test: …`, `chore: …`).
- A bumping PR/commit title carries the version in parentheses, e.g. `feat: new option (X.Y.Z)`.

## README layout
- Header order: H1, then the badge row, then the repo's **own logo** centered under the badges —
  `<p align="center"><img src=".../custom_components/hp/brand/icon.png" width="120"></p>`.
- **Brand logos**: right after the own logo, a centered `<p align="center">` row of the
  vendor logo(s) this integration targets
  (`images/*.png|svg`), each linking to the brand site where relevant.
- Keep image `width`/`height` bounded so it doesn't render oversized (HACS/Marketplace).
- The README is consumed by the **homeassistant-projects** showcase site at build — keep its
  structure intact. Keep the **Marketplace** install section (badge/button, "Settings →
  Marketplace → Add from link", `/local/community/` resources) and the **Buy Me a Coffee**
  link; the public description must not mention the author's city.

## Supported integrations
This is a **standalone integration** (its own integration, with its own card) — it talks to its device/service directly, not on top of other Home Assistant integrations — so it has **no** `## Supported integrations` section (that section is only for cards/integrations that sit on top of others). If it does build on external integrations, add the section (title verbatim).

## Translations
- English is the source. Keep every language in sync when a user-facing string changes.
- Languages to keep in sync: en, fr, de, es, it, nl, pt, pl, sr, sr-Latn, ro, da, sv, bg, ru, uk, hu, sk, cs, sl, lv, el (no Irish or Maltese).
- Integration strings: `custom_components/hp/translations/*.json` (all languages).

## Conventions
- Prefer YAML over UI configuration; keep configurations minimal; test iteratively.
- Keep `ha-*` repos **independent**: no shared/factored code across repos — duplication is fine.
- English-only README; mock/neutral data in any published screenshot.
- Call it the **Marketplace** (Home Assistant 2026.11), not HACS, in docs, issue comments
  and user replies.
- Reply to GitHub issues in the **language of the issue / reporter**, not French by default.
