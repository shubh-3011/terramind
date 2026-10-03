TerraMind Beta 1 - Windows x64
==============================

A local AI assistant for Terraform, built into a desktop editor (a Code-OSS fork).
Everything runs on your machine; no cloud account is required.


HOW TO RUN
----------
1. Double-click  TerraMind.bat   (NOT TerraMind.exe directly).

   On the first run it downloads the local AI model (~940 MB, one time only) to
   %USERPROFILE%\.terramind\models\ , starts the analysis service, then opens the
   app. Every later run starts in a second or two.

2. In the app, press Ctrl+Shift+P and try:
     - TerraMind: Analyze Terraform Workspace   (open a .tf folder first)
     - TerraMind: Generate Infrastructure (Guided)
     - TerraMind: Analyze Demo Fixture          (works with no folder)
     - TerraMind: Check Analyzer Connection


WHAT'S INSIDE
-------------
  TerraMind.exe            the desktop app
  resources/               the app + the TerraMind extension
  analyzer/                the local analysis service
    runtime/               bundled portable Python 3.13 (no install required)
    app/                   the FastAPI analyzer source
    terramind_ml/          feature extraction + risk model helpers
    models/                empty; the model is downloaded on first run
    run-analyzer.bat       starts the service with the bundled Python
  TerraMind.bat            the launcher (start here)
  README-FIRST.txt         this file


REQUIREMENTS
------------
  - Windows 10/11, 64-bit
  - ~2 GB free disk (plus ~1 GB for the model)
  - An internet connection for the first run only
  - No Python, no Node, no Ollama, no GPU required


NOTES
-----
  - The AI runs on the CPU in this beta (~10-25 tokens/second).
  - The deterministic scaffolder is instant and always returns valid Terraform for
    structured requests like "2 VPC, 2 EC2, 1 S3".
  - The generative model is a DRAFT assistant, not a correctness guarantee. Always
    run `terraform validate` / `terraform plan` before applying anything.
  - To stop everything, close the minimized "TerraMind Analyzer" window.

Licences: Code-OSS (MIT); fine-tuned models (Apache-2.0); training data includes
CC-BY-4.0 rows (attribution retained in the repository).
