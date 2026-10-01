# TerraMind architecture and API contracts

TerraMind is a Code-OSS fork. Its Terraform-specific commands and panels are built into the application source and intended to ship with TerraMind desktop downloads. They are not a separately installed Marketplace extension.

## Component responsibilities

| Component | Responsibility | Must not do |
| --- | --- | --- |
| TerraMind workbench | Collect user intent, invoke API, display diagnostics/report/diff, request user confirmation | Run `apply`, decide risk, or trust LLM output without report evidence |
| Analyzer API | Validate requests, parse bounded workspaces, optionally call static tools, invoke the experimental model and local Ollama or explicit local Transformers generation backend | Persist credentials or write generated source |
| Tool adapters | Run opt-in `terraform fmt`, pre-initialized `terraform validate`, TFLint and Checkov with timeouts, JSON capture, isolated user-home, and cloud credential scrubbing | Run `init`, `plan`, or `apply`; interpret LLM prose as tool output |
| Feature extractor | Parse Terraform/static reports into versioned numeric/categorical features | Label data from a test split |
| ML service/module | Load versioned trained model; return class, probability, calibration/version metadata | Replace deterministic findings |
| Local generation adapter | Generate Terraform drafts from bounded prompts using Ollama by default or an offline-only merged Transformers model when `TERRAMIND_HF_MODEL_PATH` is configured | Apply files or certify correctness |

## TerraMind workbench user interface

The Generate Infrastructure dialog sends four distinct inputs to the API: free-text requirements, optional resource types/counts, optional connectivity/traffic flow, and other constraints. The latter three are included in separate labeled sections of the model prompt; omitted inventory and topology are explicitly called out as unspecified. This structure helps preserve user intent but is not a correctness guarantee.

The TerraMind fork adds these first-class workbench surfaces to Code-OSS. Analyze Workspace publishes returned findings into Problems. Generate Infrastructure collects requirements, previews HCL from local Ollama or the configured local Transformers model, and writes only after explicit user save/overwrite approval. The local model gets at most one repair retry when HCL parsing fails or trusted, opt-in provider validation returns line-specific schema errors; the editor previews the final output and requires explicit save approval. This bounded retry is not a reviewable patch proposal and does not establish generation quality. When the existing **Run External Tools** setting is enabled, VS Code reports the workspace trusted, and a pre-initialized local provider cache is available, generated drafts are checked with `terraform validate` in an isolated scratch directory; this does not run `terraform init`. VS Code Restricted Mode suppresses external scanner/provider execution. The API's trust field is caller-provided, not an authentication mechanism, so the service must remain bound to loopback. Per-service summaries currently score only observed static security evidence; cost, reliability, scalability, and maintainability are explicit unknowns. Single-file user-reviewed proposals are now implemented; multi-file repairs, repair-quality evidence, and broader post-approval re-analysis guarantees remain open:

The built-in **Propose Terraform Repair** command sends only the active local `.tf` file and up to 50 TerraMind diagnostics to `POST /v1/repair`. The API returns a replacement proposal after HCL parsing and static analysis; trusted, opted-in provider validation may also run against the preinitialized cache. The API never writes. The editor opens a native diff, asks for modal approval, verifies the document content/version is unchanged, applies one workspace edit, then invokes workspace analysis again. The single-file flow is not a semantic correctness guarantee and has no interactive workbench integration test yet.

| Surface | Purpose |
| --- | --- |
| Command palette/context menu | Analyze current workspace, generate infrastructure, explain a finding, generate a repair, re-test. |
| Terraform diagnostics | Display tool findings and compatibility errors inline at relevant `.tf` locations. |
| TerraMind analysis panel | Show tool status, overall ML risk, service ratings, evidence, and actions. |
| Generate Infrastructure dialog | A guided webview form collects region, repeatable resource/count inventory rows, connected-topology text, and constraints, then previews the generated draft. |
| Draft preview | Show generated HCL, static AWS findings, evidence-limited service ratings, and optional cached-provider validation findings before the user chooses an in-workspace path. |

## Rating contract

Every service/project rating returned by the backend must include source and confidence, so the UI never conflates a rule violation with an ML prediction:

```json
{
  "scope": "aws_db_instance.primary",
  "dimension": "reliability",
  "score": 5,
  "max_score": 10,
  "status": "rated",
  "criteria_version": "aws-rubric-v1",
  "evidence_finding_ids": ["checkov-12"],
  "assumptions": ["availability_target=99.9%"],
  "limitations": ["Runtime load and managed-service incidents are unknown"]
}
```

Use `status: "insufficient_information"` rather than fabricating a rating when Terraform and stated assumptions cannot support it.

As of `aws-rubric-v2`, `security`, `reliability`, and `maintainability` are scored from observable evidence; each scored dimension also carries `evidence` (structural facts such as `aws_db_instance.primary: multi_az=false`), `evidence_finding_ids`, `assumptions`, and `limitations`. `scalability` and `cost` deliberately remain `insufficient_information` because they require external workload and pricing data. Reliability is scored only when resources expose relevant resilience attributes; maintainability is scored only when structural signals (tags, variable references, modules, pinned providers) are observable.

## Analysis job lifecycle

```text
QUEUED -> PRECHECK -> FORMATTING -> VALIDATING -> SCANNING -> FEATURIZING
       -> PREDICTING -> [EXPLAINING] -> COMPLETED | FAILED | CANCELLED
```

Every job stores tool versions, status, duration, normalized findings, and a workspace fingerprint. Failed or skipped steps have explicit reasons; a skipped `plan` is not a failed plan.

## Core REST contracts (MVP)

### `POST /v1/analyze` (current static-analysis slice)

Request:

```json
{"workspace_path":"/approved/workspace"}
```

Current synchronous response:

```json
{
  "status":"completed",
  "terraform_file_count":2,
  "parsed_file_count":2,
  "findings":[{"id":"main.tf:TM-NET-001:4","source":"terramind-rules","severity":"error","file":"main.tf","line":4,"rule_id":"TM-NET-001","message":"...","recommendation":"..."}],
  "risk_prediction":{"source":"experimental-ml","model_version":"terraform-risk-iacsecbench-v1","label":"elevated_observed_control_risk","probability":0.72,"calibrated":false},
  "checks":{"hcl_parse":"completed","terraform_validate":"not_run: ...","tflint":"not_run: ...","checkov":"not_run: ...","ml_risk":"experimental: terraform-risk-iacsecbench-v1"}
}
```

The current implementation uses `python-hcl2` to parse `.tf` files and an extensible deterministic registry under `app/rules/` (45 rules as of 2026-10-01) grouped by domain: networking (`TM-NET-*`), IAM/KMS (`TM-IAM-*`), S3/EBS/EFS storage (`TM-STOR-*`), databases (`TM-DB-*`), compute (`TM-COMPUTE-*`), observability (`TM-OBS-*`), and secrets hygiene (`TM-SECRET-*`), plus the original inline checks (`TM-HCL-001` parser error, `TM-NET-001` public SSH, `TM-NET-003` unresolved dynamic ingress, `TM-IAM-001/002`, `TM-S3-001/002`, `TM-ECR-001`, `TM-EC2-001`, `TM-EBS-001`). Each rule is a pure function over the parsed document and carries severity, service, dimension, and remediation metadata; a failing rule is isolated and skipped. `/v1/analyze` and `/v1/generate` additionally return a severity-ranked recommendation list grouped by rule. Optional external tools are off by default and require `run_external_tools=true`; TerraMind never initializes a workspace or runs plan/apply. `terraform validate` runs only when an existing provider installation is found and can execute those installed plugins, so the user must trust the workspace before opting in. Tool output is bounded and child processes receive no cloud credentials. File discovery excludes `.terraform`, `.git`, and `node_modules`, skips external symlink targets, and enforces file-count/size limits.

When a compatible model artifact exists and every Terraform file parses, the API returns a separate experimental estimate trained on a small, generated AWS control corpus. The estimate is uncalibrated, reports the training sample count, and may be absent when a file failed parsing or the artifact is missing. It predicts benchmark-control violation labels only—not cloud runtime outcomes.

**Local-service security status:** the API accepts a workspace path from its local caller and does not yet implement a configured path allowlist or request authorization. Bind it only to loopback for development. Do not expose the service beyond the local machine.

### `POST /v1/generate` (implemented, local model required)

Request contains a bounded description, constraints, workspace path, optional installed Ollama model name, external-tools opt-in flag, and the extension-reported workspace-trusted state. The API talks only to loopback Ollama by default or an explicitly configured local Transformers model. It parses the HCL, runs deterministic security rules, and may run `terraform validate` against providers already installed in that workspace. On a parse or provider-schema error it may send one repair prompt containing the draft and diagnostics, then re-parse and revalidate. Validation copies/hard-links the provider cache and lockfile into a disposable scratch directory, strips cloud/`TF_*` credentials, invokes no shell, and never runs `init`, `plan`, or `apply`. It returns findings and limited service ratings without writing generated source to the workspace. The editor previews the final draft; saving is user initiated. The trust field is not authentication; callers can forge it, so keep the API on loopback. References requiring uninstalled modules/providers, external scanners, costs, and runtime/deployment behavior may remain unverified.

Response includes the HCL and scope disclaimer, and the same finding/service-rating shapes used by workspace analysis:

```json
{
  "status": "completed",
  "syntax_valid": true,
  "validation_scope": "HCL syntax/static checks; terraform_validate=not_run: external tools disabled.",
  "findings": [{"id": "main.tf:TM-NET-001:2", "source": "terramind-rules", "rule_id": "TM-NET-001", "severity": "error", "file": "main.tf", "line": 2, "message": "..."}],
  "service_ratings": [{"service": "networking", "resource_count": 1, "dimensions": {"security": {"score": 65, "status": "limited", "evidence_finding_ids": ["main.tf:TM-NET-001:2"]}, "reliability": {"score": null, "status": "insufficient_information"}}}],
  "checks": {"hcl_parse": "passed", "terraform_validate": "not_run: external tools disabled"}
}
```

### `POST /v1/repair-proposals`

Request contains `workspace_path`, `analysis_job_id`, and optional user intent. Response:

```json
{"proposal_id":"uuid","unified_diff":"diff --git ...","rationale":"...","grounded_finding_ids":["finding-1"],"warnings":["Re-run analysis before use"]}
```

### `POST /v1/reports/{job_id}/explanation`

Uses only the normalized report and selected code excerpts. Return a concise explanation marked `source: "llm"`; it must link back to finding IDs and prediction metadata.

## Boundary and security rules

- Canonicalize `workspace_path`; reject paths outside the extension-approved workspace root.
- Use a per-job copy/work directory where a tool may write files.
- Enforce CPU/time/output limits; scrub environment variables passed to child processes.
- Default `run_plan` to false. If enabled, use a documented safe mode and never invoke `apply`.
- Use JSON outputs where tools support them; preserve raw outputs only as local debug artifacts.
- Model and tool results include versions and timestamps for reproducibility.
