# Private GitHub repository

The repository is already created and pushed as a private repository:
[shubh-3011/terramind](https://github.com/shubh-3011/terramind).

## Current remote layout

- `origin`: the private TerraMind repository; `main` is the working branch.
- `upstream`: Microsoft Code-OSS (`microsoft/vscode`) for source reference and future updates.
- Initial history: `main` starts from a full source snapshot commit rather than importing all upstream Git history. See [PROGRESS.md](../PROGRESS.md).

## Safe push workflow

Before each push:

1. Run the relevant tests/build checks.
2. Review `git status` and `git diff --cached`.
3. Confirm `.env`, credentials, Terraform state/plans, `node_modules`, local build outputs, and raw benchmark HCL are not staged. The small derived feature CSV, source manifest, JSON model, and metrics report are intentionally tracked in this private repository.
4. Use a descriptive commit message for a complete feature or documentation milestone.
5. Push `main` and verify the remote commit.

Do not create empty or duplicate commits to inflate contribution counts. Keep commits small enough to review but meaningful; GitHub contribution graphs do not benefit from repeated pushes of the same content.

The plan, architecture, progress, and project brief are included in this private repository by owner decision. Treat repository access as limited to intended collaborators; private visibility is not a substitute for excluding secrets or regulated data.

## GitHub Actions status

The TerraMind extension participates in the repository's npm-workspace cache key and therefore requires its own `package-lock.json`. The Monaco and telemetry workflows require `contents: read` to check out this private repository. Dependabot PRs use read-only tokens, so the CodeQL upload job is skipped for those dependency-only PRs based on the PR author's login; normal PRs and scheduled scans retain CodeQL. Linux workflows invoke `apt-retry.sh` through `bash`, because the helper is tracked without its executable bit. These fixes were pushed on 2026-09-29 and merged into five open Dependabot branches. A fresh Linux Electron-Unit run passed system setup and advanced past the repaired apt helper into dependency installation; the full job was still in progress at last inspection. macOS jobs remain blocked by the account billing/spending limit, while Microsoft-only self-hosted jobs are unavailable to this private fork.

The `terramind-ml-validation.yml` workflow rebuilds the dataset from its pinned public benchmark, runs tests, retrains the model, and uploads the evaluation output. Dataset comparison normalizes platform line endings while requiring identical content. The `terramind-builds.yml` workflow creates short-lived Windows/Linux preview artifacts from `testing`; a `terramind-v*` tag can create a draft private release after both platform builds succeed. Initial hosted attempts found a bad relative path and CRLF/LF mismatch in the dataset comparison plus missing platform-native build preparation and dependency sequencing for packaging; fixes are on `testing`, and successful reruns are still required. The analyzer API still requires manual startup, so these are alpha downloads rather than end-user releases.
