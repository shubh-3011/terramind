# TerraMind Code-OSS fork strategy

> **Status (2026-10-03):** the fork is built and shipped — `npm run gulp vscode-win32-x64-min` produces `VSCode-win32-x64\TerraMind.exe`, which is packaged into the public **Beta 1** portable ZIP (app + bundled analyzer + launcher). The earlier `@vscode/policy-watcher` startup hang is fixed. See [DISTRIBUTION.md](DISTRIBUTION.md).

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

The current MVP is estimated at roughly 65% complete by milestone coverage. Local inference, scanner adapters, evidence ratings, corpus preparation, a short LoRA smoke training path, optional Transformers-backed inference, separate generation inputs for requirements/inventory/topology/constraints, a one-retry parser/provider feedback loop, and a single-file repair proposal with user-approved diff preview are implemented. The post-retry three-example smoke run parsed 2/3 outputs; cached AWS provider validation accepted 0/2 parseable drafts after retry. These are pipeline checks, not a quality benchmark. Repair semantics, interactive UI tests, useful-scale independent model evaluation, successful hosted CI, and full desktop build validation remain. GitHub currently prevents ML/package jobs from starting due to account payment/spending-limit restrictions. See the local progress log.

- Code-OSS source snapshot imported and Microsoft VS Code retained as `upstream` remote.
- TerraMind product identity and internal contribution are present.
- Analyzer API and built-in Analyze/Generate commands are present: HCL parse, AWS static rules (including in-memory checks on generated drafts), opt-in preinitialized-cache Terraform validation/TFLint/Checkov integration, ML risk estimate, Problems diagnostics, local Ollama/optional Transformers draft preview and explicit save.
- A compact, grouped-evaluation experimental logistic model is available; it is not a general Terraform code-generation model or production predictor.
- Analyzer/ML/data/training/evaluation tests pass (40); the extension TypeScript project typecheck passes. Full Code-OSS extension packaging cannot run in this checkout because its Gulp file is absent.
- Full Code-OSS install/build/launch is **not verified**; Windows native build prerequisites and GitHub's upstream-specific self-hosted runners remain outstanding. See the latest build/CI entry in the local progress log.
- A testing-branch workflow targets downloadable Windows x64 ZIP and Linux x64 TAR.GZ preview builds. A `terramind-v*` tag can create a draft private release only after both builds succeed; current hosted jobs are not yet verified. These alpha packages still require the analyzer API and Ollama to be started manually and are not end-user-ready.

## Next technical milestones

1. Complete the native prerequisites and verify a branded development launch.
2. Add analyzer workspace allowlisting and stable rules/tests for more invalid and insecure configurations.
3. Install/run the local model; fine-tune and benchmark an adapter only after GPU training dependencies and corpus licensing are verified.
4. Add reliability/cost/scalability ratings that show their criteria and insufficient-information states.
5. Add grounded explanations and multi-file repair support; verify repeated analyzer feedback after approved single-file repairs.

## Development requirements and maintenance

Expect a significantly larger source tree and build than an ordinary VS Code extension. Current Code-OSS contributor guidance uses Yarn 1, Python for `node-gyp`, and a C/C++ toolchain on Windows; validate exact versions against the pinned upstream revision before setup. [Code-OSS contributor build guidance](https://github.com/microsoft/vscode/wiki/How-to-Contribute)

Maintain an `upstream/<version>` branch and periodically merge or rebase tested upstream updates. Do not use Microsoft's Visual Studio Code branding, identifiers, or distribution services. Keep Code-OSS licensing/notices with the redistributed application.
