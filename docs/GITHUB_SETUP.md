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
3. Confirm `.env`, credentials, Terraform state/plans, `node_modules`, local build outputs, and model/data artifacts are not staged.
4. Use a descriptive commit message for a complete feature or documentation milestone.
5. Push `main` and verify the remote commit.

Do not create empty or duplicate commits to inflate contribution counts. Keep commits small enough to review but meaningful; GitHub contribution graphs do not benefit from repeated pushes of the same content.

The plan, architecture, progress, and project brief are included in this private repository by owner decision. Treat repository access as limited to intended collaborators; private visibility is not a substitute for excluding secrets or regulated data.
