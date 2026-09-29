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

The TerraMind fork adds these first-class workbench surfaces to Code-OSS. Analyze Workspace publishes returned findings into Problems. Generate Infrastructure collects requirements, previews HCL from local Ollama or the configured local Transformers model, and writes only after explicit user save/overwrite approval. When the existing **Run External Tools** setting is enabled, VS Code reports the workspace trusted, and a pre-initialized local provider cache is available, the generated draft is also checked with `terraform validate` in an isolated scratch directory before preview; this does not run `terraform init`. VS Code Restricted Mode suppresses external scanner/provider execution. The API's trust field is caller-provided, not an authentication mechanism, so the service must remain bound to loopback. Per-service summaries currently score only observed static security evidence; cost, reliability, scalability, and maintainability are explicit unknowns. Repair remains planned:

| Surface | Purpose |
| --- | --- |
| Command palette/context menu | Analyze current workspace, generate infrastructure, explain a finding, generate a repair, re-test. |
| Terraform diagnostics | Display tool findings and compatibility errors inline at relevant `.tf` locations. |
| TerraMind analysis panel | Show tool status, overall ML risk, service ratings, evidence, and actions. |
| Generate Infrastructure dialog | Collect free-text intent and constraints; structured region/resource/workload fields remain planned. |
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

The current implementation uses `python-hcl2` to parse `.tf` files and deterministic rules: `TM-NET-001` public SSH ingress (including supported literal dynamic ingress); `TM-NET-003` unresolved dynamic ingress for manual review; `TM-IAM-001/002` wildcard actions/resources; `TM-S3-001/002` disabled S3 public-access protections/public ACLs; `TM-ECR-001` mutable image tags; `TM-EC2-001` optional IMDSv2 tokens; and `TM-EBS-001` explicit disabled EBS encryption. `TM-HCL-001` is a parser error. Optional external tools are off by default and require `run_external_tools=true`; TerraMind never initializes a workspace or runs plan/apply. `terraform validate` runs only when an existing provider installation is found and can execute those installed plugins, so the user must trust the workspace before opting in. Tool output is bounded and child processes receive no cloud credentials. File discovery excludes `.terraform`, `.git`, and `node_modules`, skips external symlink targets, and enforces file-count/size limits.

When a compatible model artifact exists and every Terraform file parses, the API returns a separate experimental estimate trained on a small, generated AWS control corpus. The estimate is uncalibrated, reports the training sample count, and may be absent when a file failed parsing or the artifact is missing. It predicts benchmark-control violation labels only—not cloud runtime outcomes.

**Local-service security status:** the API accepts a workspace path from its local caller and does not yet implement a configured path allowlist or request authorization. Bind it only to loopback for development. Do not expose the service beyond the local machine.

### `POST /v1/generate` (implemented, local model required)

Request contains a bounded description, constraints, workspace path, optional installed Ollama model name, external-tools opt-in flag, and the extension-reported workspace-trusted state. The API talks only to loopback Ollama by default or an explicitly configured local Transformers model. It parses the HCL, runs the existing deterministic security rules in memory, and may run `terraform validate` against provider binaries already installed in that workspace. Validation copies/hard-links the provider cache and lockfile into a disposable scratch directory, strips cloud/`TF_*` credentials, invokes no shell, and never runs `init`, `plan`, or `apply`. It returns findings and limited service ratings without writing generated source to the workspace. The editor previews the code and findings; saving is user initiated. The trust field is not authentication; callers can forge it, so keep the API on loopback. References requiring uninstalled modules/providers, external scanners, costs, and runtime/deployment behavior may remain unverified.

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
