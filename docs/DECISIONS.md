# Architecture decisions

## D-001: Ship TerraMind as a Code-OSS fork

**Status:** accepted; implementation scaffolded.

TerraMind is a branded desktop editor built from Code-OSS. The Terraform-specific contribution may be implemented as bundled internal extension code, but users should not need to install it from the Marketplace. This matches the requested product experience. A full app build remains unverified due to Windows native build prerequisites.

## D-002: Terraform and AWS only in version 1

**Status:** accepted for MVP.

Provider-specific feature extraction and controlled mutations are necessary for credible evaluation. Restricting to AWS makes the data and demo tractable.

## D-003: Analysis is local and non-destructive

**Status:** accepted for MVP.

The backend may run formatting, validation, static analyzers, and a guarded plan. It must not call `terraform apply`, create cloud resources, or retain cloud credentials.

## D-004: Traditional ML is separate from the LLM

**Status:** accepted for MVP.

The trained risk model consumes engineered features and exposes probability, class, model version, and evidence. LLM generation/explanation is an optional local service and is not used as a ground-truth evaluator.

## D-005: Risk model is the required ML deliverable

**Status:** accepted for MVP.

Start with one binary risk model (risk/failure probability). Failure-category classification and a quality score are optional only after the primary model is evaluated with group-safe splits, calibration, and baselines.

## D-006: Patches require preview and user approval

**Status:** accepted for MVP.

**Planned:** the backend returns unified diffs. The extension shows the diff and applies it only through a user-confirmed workspace edit, then re-runs analysis. No generation or repair implementation exists yet.

## D-007: Start analysis with static checks and evidence labels

**Status:** accepted; first slice implemented.

Use HCL parsing and transparent deterministic rules before invoking provider plugins or external scanners. Mark every check as completed, skipped, or unavailable. Never imply that current heuristics equal `terraform validate`, Checkov, TFLint, cost estimates, uptime guarantees, or an ML prediction.

## D-008: Train a separate, conservative risk estimator

**Status:** accepted; experimental prototype trained.

Use a traditional, inspectable classifier over versioned numeric features rather than fine-tuning a foundation model on a tiny corpus. The initial logistic model uses a pinned, MIT-licensed controlled corpus, excludes case identifiers/comments from features, and groups paired variants during cross-validation. Label its output as experimental and uncalibrated; do not equate a benchmark-control violation score with deployment failure, uptime, scalability, or cost.
