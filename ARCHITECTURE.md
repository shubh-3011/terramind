# TerraMind architecture and API contracts

TerraMind is a Code-OSS fork. Its Terraform-specific commands and panels are built into the application source and released with the TerraMind installer. They are not a separately installed Marketplace extension.

## Component responsibilities

| Component | Responsibility | Must not do |
| --- | --- | --- |
| TerraMind workbench | Collect user intent, invoke API, display diagnostics/report/diff, request user confirmation | Run `apply`, decide risk, or trust LLM output without report evidence |
| Analyzer API | Validate requests, create isolated analysis jobs, call tools, normalize results, invoke model/LLM adapters | Persist credentials or mutate source workspace without explicit patch request |
| Tool adapters | Execute Terraform, TFLint, Checkov with timeouts and structured capture | Interpret LLM prose as tool output |
| Feature extractor | Parse Terraform/static reports into versioned numeric/categorical features | Label data from a test split |
| ML service/module | Load versioned trained model; return class, probability, calibration/version metadata | Replace deterministic findings |
| Ollama adapter | Generate code/explanation/diff from bounded prompt context and analysis report | Apply files or certify correctness |

## TerraMind workbench user interface

The TerraMind fork adds these first-class workbench surfaces to Code-OSS. Currently, Analyze Workspace publishes returned findings into the built-in Problems collection and shows summary counts; generation, rating, and repair surfaces below remain planned:

| Surface | Purpose |
| --- | --- |
| Command palette/context menu | Analyze current workspace, generate infrastructure, explain a finding, generate a repair, re-test. |
| Terraform diagnostics | Display tool findings and compatibility errors inline at relevant `.tf` locations. |
| TerraMind analysis panel | Show tool status, overall ML risk, service ratings, evidence, and actions. |
| Generate Infrastructure dialog | Collect free-text intent plus region, resource counts, connectivity, workload, budget, and availability requirements. |
| Diff preview | Show LLM-generated files or repair changes before an explicit apply action. |

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
  "checks":{"hcl_parse":"completed","terraform_validate":"not_run: ...","tflint":"not_run: ...","checkov":"not_run: ...","ml_risk":"not_available: ..."}
}
```

The current implementation uses `python-hcl2` to parse `.tf` files and two initial rules: `TM-NET-001` for public SSH ingress and `TM-IAM-001` for literal wildcard IAM actions. `TM-HCL-001` is a parser error. Findings are static heuristics, not Terraform provider validation, scanner results, or model predictions. File discovery excludes `.terraform`, `.git`, and `node_modules`, skips external symlink targets, and enforces file-count/size limits. It does not run `terraform init`, providers, `terraform validate`, TFLint, or Checkov.

**Local-service security status:** the API currently accepts a workspace path from its local caller and does not yet implement a configured path allowlist. Bind it only to loopback for development. Add an explicit approved-root boundary and request authorization before enabling external-tool execution or exposing the service beyond the local machine.

### `POST /v1/generation`

Request contains `prompt`, approved `workspace_path`, and an optional file-layout template. Response contains generated files plus an `AnalysisReport`; files are staged only, never written silently.

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
