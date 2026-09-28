"""Local API boundary for Terraform analysis."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="TerraMind Analyzer", version="0.0.1")


class AnalyzeRequest(BaseModel):
    """A request to inspect Terraform files in one local workspace."""

    workspace_path: str


class AnalyzeResponse(BaseModel):
    """The minimal result returned before external analyzer integration."""

    status: str
    terraform_file_count: int


@app.get("/health")
def health() -> dict[str, str]:
    """Return service availability without touching a workspace."""
    return {"status": "ok"}


@app.post("/v1/analyze", response_model=AnalyzeResponse)
def analyze_workspace(request: AnalyzeRequest) -> AnalyzeResponse:
    """Count Terraform files while the deterministic tool runner is being added."""
    workspace = Path(request.workspace_path).expanduser().resolve()
    if not workspace.is_dir():
        raise HTTPException(status_code=400, detail="workspace_path must be an existing directory")

    terraform_files = [
        path
        for path in workspace.rglob("*.tf")
        if ".terraform" not in path.parts
    ]
    return AnalyzeResponse(status="accepted", terraform_file_count=len(terraform_files))
