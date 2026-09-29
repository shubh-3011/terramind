# TerraMind Code-OSS fork strategy

## Decision

TerraMind will be a separate desktop editor built from the open-source Code-OSS repository, not a Marketplace extension. Users install and launch **TerraMind** as their editor; its Terraform intelligence features are built in.

## What is reused and what changes

Code-OSS provides the editor, terminal, file explorer, editor tabs, workbench, debugging architecture, and extension host. TerraMind changes its product identity and adds a built-in Terraform intelligence contribution.

| Area | TerraMind change |
| --- | --- |
| Product identity | Set a unique TerraMind name, application ID, data-folder name, URL protocol, icons, Windows identifiers, and update channel. |
| Workbench | Add a TerraMind activity-bar container, analysis panel, generation dialog, result views, and commands. |
| Diagnostics | Publish Terraform analyzer results in the existing Problems/editor diagnostic experience. |
| Local service bridge | Spawn/connect to the local analyzer API; show startup, unavailable, and timeout states. |
| Packaging | Produce a TerraMind Windows installer/development build; retain required Code-OSS license notices. |

Code-OSS exposes product naming and related distribution values in `product.json`; Microsoft documents that most distribution customization lives there. [Code-OSS product configuration](https://github.com/microsoft/vscode/blob/main/product.json)

## Repository layout

Relevant TerraMind-specific paths within the current Code-OSS fork:

```text
terramind/
  product.json                  TerraMind branding/distribution configuration
  src/vs/workbench/contrib/terramind/
                                native workbench feature source
  extensions/terramind-core/    built-in internal contribution, shipped with app
  services/analyzer-api/        local Python analyzer + ML inference
  data/manifests/               local reproducible dataset manifests
  docs/                         project architecture, build, dataset, and demo notes (published in the private repository)
```

It is acceptable to implement part of the product feature as a **bundled internal extension** under `extensions/` because it ships in the TerraMind application and is not installed by end users. Workbench-level branding, navigation, and product integration remain in the fork source.

## Current implementation status (2026-09-29)

The current MVP is estimated at roughly 35–40% complete by milestone coverage. The workbench's analyzer/ML foundation is in place, but there is no full desktop build, generation/repair flow, or packaged release yet. See the milestone breakdown in [PROGRESS.md](../PROGRESS.md).

- Code-OSS source snapshot imported and Microsoft VS Code retained as `upstream` remote.
- TerraMind product identity and internal contribution are present.
- Analyzer API and first-pass Analyze command are present: HCL parse, AWS static rules, ML risk estimate, and Problems diagnostics.
- A compact, grouped-evaluation experimental logistic model is available; it is not a general Terraform code-generation model or production predictor.
- TerraMind extension compilation passes with 0 TypeScript errors; analyzer/ML tests pass (11).
- Full Code-OSS install/build/launch is **not verified**; Windows native build prerequisites and GitHub's upstream-specific self-hosted runners remain outstanding. See the latest build/CI entry in [PROGRESS.md](../PROGRESS.md).
- A testing-branch workflow now targets downloadable Windows x64 ZIP and Linux x64 TAR.GZ preview builds. A `terramind-v*` tag produces a draft private release only after both builds succeed; no package is published until a successful run. These alpha packages still require the analyzer API to be started manually and are not end-user-ready.

## Next technical milestones

1. Complete the native prerequisites and verify a branded development launch.
2. Add analyzer workspace allowlisting and stable rules/tests for more invalid and insecure configurations.
3. Add Terraform CLI, TFLint, and Checkov integrations with bounded process time and explicit skipped-tool states.
4. Finish diagnostic mappings and analyzer lifecycle UX in the workbench.
5. Add AI generation only after the deterministic analysis stage can test generated code.

## Development requirements and maintenance

Expect a significantly larger source tree and build than an ordinary VS Code extension. Current Code-OSS contributor guidance uses Yarn 1, Python for `node-gyp`, and a C/C++ toolchain on Windows; validate exact versions against the pinned upstream revision before setup. [Code-OSS contributor build guidance](https://github.com/microsoft/vscode/wiki/How-to-Contribute)

Maintain an `upstream/<version>` branch and periodically merge or rebase tested upstream updates. Do not use Microsoft's Visual Studio Code branding, identifiers, or distribution services. Keep Code-OSS licensing/notices with the redistributed application.
