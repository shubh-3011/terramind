# Repository setup and orientation

> **Status (2026-10-03):** TerraMind is published from a **public** repository
> ([`shubh-3011/terramind`](https://github.com/shubh-3011/terramind), default branch `main`) while
> active development continues on a **private** mirror
> ([`shubh-3011/terramind-dev`](https://github.com/shubh-3011/terramind-dev), `testing` branch).
> The model is hosted on Hugging Face. GitHub Actions is disabled.

This document orients a new contributor or agent: which repositories exist, what each holds, how
the model is hosted, how releases ship, where the planning notes live, and why CI is off. It is
the map for everything else in `docs/`.

---

## Remotes and branches

The working checkout has three git remotes. The public/private split is the important one.

| Remote | URL | Role |
| --- | --- | --- |
| `origin` | `https://github.com/shubh-3011/terramind.git` | **Public.** Only `main` is published here. |
| `dev` | `https://github.com/shubh-3011/terramind-dev.git` | **Private mirror.** Holds `testing` and in-progress work. |
| `upstream` | `https://github.com/microsoft/vscode.git` | Code-OSS source reference; not a TerraMind remote. |

| Branch | Tracks | Notes |
| --- | --- | --- |
| `main` | `origin/main` | The **only** branch published publicly. Stable, release-ready documentation. |
| `testing` | `dev/testing` | Private development branch. Land work here first; promote to `main` when ready. |

`origin` is deliberately kept minimal: pushing `testing` or private work to `origin` would publish
it. Do development pushes against `dev`. When a change is ready for the public, merge it onto
`main` and push `main` to `origin`.

```powershell
git fetch dev
git switch testing            # tracks dev/testing
git switch main
git merge --ff-only testing   # publish only when intentionally ready
git push origin main
```

---

## Model hosting (Hugging Face)

The bundled generator is a ~940 MB `Q4_K_M` GGUF. It is **not** committed to Git (`.gitignore`
ignores `*.gguf`). It is hosted on Hugging Face as the primary source:

- Repository: **https://huggingface.co/shubh-3011/terramind-qwen2.5-coder-1.5b-terraform** (public)
- Direct file URL:
  `https://huggingface.co/shubh-3011/terramind-qwen2.5-coder-1.5b-terraform/resolve/main/terramind-qwen2.5-coder-v2-merged-Q4_K_M.gguf`

The **single source of truth** for where the app downloads the model is the `MODEL_URL` variable
at the top of the launcher, `packaging\TerraMind.bat`. The bundled analyzer is host-agnostic, so
changing the host is a one-line edit plus a re-release of the launcher (see
[DISTRIBUTION.md](DISTRIBUTION.md)).

**To change `MODEL_URL`:**
1. Upload (or pick) the GGUF and copy its direct `.../resolve/main/<file>.gguf` URL.
2. Edit `MODEL_URL` at the top of `packaging\TerraMind.bat`; keep it a raw file URL that
   `curl`/`Invoke-WebRequest` can fetch without authentication.
3. Note the new SHA-256 so users can verify the download, then rebuild/re-release the launcher.
4. Update [MODEL_CARD.md](MODEL_CARD.md) and [DISTRIBUTION.md](DISTRIBUTION.md) if the artifact name
   or checksum changes.

The GitHub release keeps the GGUF as a **fallback** asset, so the download still works if Hugging
Face is unreachable. No secrets are needed for either source — both are public.

---

## Release and distribution model

The current public release is **`v0.1.0-beta.1`** on `origin`:

- **`TerraMind-beta1-win32-x64-full.zip`** — the self-contained portable build: the desktop app
  **plus** the bundled analyzer with a portable CPU Python runtime.
- The **GGUF** as a fallback model asset (the Hugging Face copy above is primary).

The portable launcher and build script are version-controlled in **`packaging/`**. That folder is
the home for `TerraMind.bat` and the packaging build script, so the launcher that end users run and
the script that produces the ZIP live in Git rather than only in local build output.

On first run the launcher:
1. downloads the ~940 MB model (once) into `%USERPROFILE%\.terramind\models\`,
2. starts the analyzer on `127.0.0.1:8000`, and
3. opens the app.

See [DISTRIBUTION.md](DISTRIBUTION.md) for the bundle layout, sizes, and build steps, and
[FORK_BUILD.md](FORK_BUILD.md) for the Code-OSS build.

---

## Where the planning docs live

Internal planning notes are kept **local only** — untracked and ignored by `.gitignore` — and are
**not published** to either GitHub repository:

| Local file | Purpose |
| --- | --- |
| `PLAN.md` | Roadmap and milestone plan |
| `PROGRESS.md` | Running progress log |
| `ARCHITECTURE.md` | Internal architecture notes |
| `current-issue-progress.md` | Current issue/status scratchpad |

Do not commit these or reference them from published docs. The public `docs/` set (including this
file) is the contributor-facing documentation. The private `dev` mirror may carry additional
private work, but the planning notes above stay on the local machine.

---

## CI situation

**GitHub Actions is disabled** at the repository level. The inherited Code-OSS workflows
(`pr*.yml`, `codeql.yml`, `monaco-editor.yml`, …) and `.github/dependabot.yml` were **removed**;
they failed on every push under the account's Actions billing block. Nothing runs automatically:
tests and builds are executed locally before a push.

- Tests: `services/analyzer-api` with `pytest`, plus the extension TypeScript check.
- Build: `npm run gulp vscode-win32-x64-min`, then package with the `packaging/` script.

Because there is no CI gate, run the relevant checks yourself and review `git status` /
`git diff --cached` before pushing (see [GITHUB_SETUP.md](GITHUB_SETUP.md) for the historical safe
push workflow). Never stage `.env`, credentials, Terraform state/plans, `node_modules`, build
output, or raw model weights.

---

## Quick reference

| Thing | Location |
| --- | --- |
| Public code | https://github.com/shubh-3011/terramind (`main`) |
| Private dev mirror | https://github.com/shubh-3011/terramind-dev (`testing`, remote `dev`) |
| Model (primary) | https://huggingface.co/shubh-3011/terramind-qwen2.5-coder-1.5b-terraform |
| Model (fallback) | `v0.1.0-beta.1` release asset |
| Release download | https://github.com/shubh-3011/terramind/releases/latest |
| Launcher / build | `packaging/` |
| Planning docs | Local only: `PLAN.md`, `PROGRESS.md`, `ARCHITECTURE.md`, `current-issue-progress.md` |
| CI | Disabled (no GitHub Actions) |
