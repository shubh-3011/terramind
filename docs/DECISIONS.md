# Architecture decisions

## D-001: Ship TerraMind as a Code-OSS fork

**Status:** accepted; implementation scaffolded.

TerraMind is a branded desktop editor built from Code-OSS. The Terraform-specific contribution may be implemented as bundled internal extension code, but users should not need to install it from the Marketplace. This matches the requested product experience. A full app build remains unverified due to Windows native build prerequisites.

## D-002: Terraform and AWS only in version 1

**Status:** accepted for MVP; static integrations implemented opt-in.

Provider-specific feature extraction and controlled mutations are necessary for credible evaluation. Restricting to AWS makes the data and demo tractable.

## D-003: Analysis is local and non-destructive

**Status:** accepted for MVP.

The backend may run formatting, validation, and static analyzers. These integrations default off; `terraform validate` is limited to already-initialized provider plugins, and the runner scrubs cloud credentials. TerraMind must not initialize, plan, apply, create cloud resources, or retain cloud credentials.

## D-004: Traditional ML is separate from the LLM

**Status:** accepted for MVP.

The trained risk model consumes engineered features and exposes probability, class, model version, and evidence. LLM generation/explanation is an optional local service and is not used as a ground-truth evaluator.

## D-005: Risk model is the required ML deliverable

**Status:** accepted for MVP.

Start with one binary risk model (risk/failure probability). Failure-category classification and a quality score are optional only after the primary model is evaluated with group-safe splits, calibration, and baselines.

## D-006: Patches require preview and user approval

**Status:** accepted for MVP.

**Status:** generated drafts preview before the user explicitly saves to a selected path inside the current workspace; overwrites require another confirmation. Repair diffs and an automatic full verification loop remain planned.

## D-007: Start analysis with static checks and evidence labels

**Status:** accepted; first slice implemented.

Use HCL parsing and transparent deterministic rules before invoking provider plugins or external scanners. Mark every check as completed, skipped, or unavailable. Never imply that current heuristics equal `terraform validate`, Checkov, TFLint, cost estimates, uptime guarantees, or an ML prediction.

## D-008: Train a separate, conservative risk estimator

**Status:** accepted; experimental prototype trained and wired to analyzer/UI.

Use a traditional, inspectable classifier over versioned numeric features rather than fine-tuning a foundation model on a tiny corpus. The initial logistic model uses a pinned, MIT-licensed controlled corpus, excludes case identifiers/comments from features, and groups paired variants during cross-validation. Label its output as experimental and uncalibrated; do not equate a benchmark-control violation score with deployment failure, uptime, scalability, or cost.

## D-009: Keep generation data separate and attributed

**Status:** accepted; preparation pipeline implemented, model fine-tuning not yet run.

Use the pinned CC-BY-4.0 terraform-multicloud dataset only for optional NL-to-HCL training, preserve per-row repository/license attribution, filter to parseable AWS HCL and repository-disjoint splits, and keep prepared raw text out of Git. This corpus is not security, cost, reliability, or deployment ground truth.
