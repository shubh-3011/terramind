# Open-sourcing TerraMind: release checklist

This is a practical, honest checklist for publishing TerraMind as an open-source project. It
covers the two licenses that govern the **code**, the attribution obligations for the **model and
dataset**, where to host the **GGUF**, and how end users run the model **without installing their
own Ollama**. Work top to bottom; the last section is a copy-paste checklist.

## 1. Source code licensing

TerraMind is a fork of **Code-OSS** (the open-source core of VS Code), so it inherits that
license and must keep its notices.

- [ ] **Code-OSS base is MIT.** `LICENSE.txt` is the MIT license, © Microsoft Corporation. Keep it
      in the root of the repository and do not remove or replace it. See
      [microsoft/vscode](https://github.com/microsoft/vscode) for the upstream text.
- [ ] **The TerraMind extension is MIT.** `extensions/terramind-core/package.json` declares
      `"license": "MIT"`. Add a matching MIT `LICENSE` for the extension at publish time so the
      Marketplace/npm metadata and the bundled license agree.
- [ ] **Do not ship Microsoft branding.** The MIT license covers the Code-OSS source, but it does
      **not** grant rights to Microsoft trademarks, product icons, the VS Code brand, or the
      proprietary Visual Studio Marketplace. TerraMind already rebrands via `product.json`
      (`nameShort: "TerraMind"`, `licenseUrl` pointing at the MIT license). Keep the rebrand: do
      not restore VS Code icons/names and do not ship Microsoft-proprietary code or the official
      Marketplace.
- [ ] **Regenerate third-party notices.** `ThirdPartyNotices.txt` and `cglicenses.json` enumerate
      bundled dependencies. Re-run the repo's notice/license tooling and review the diff before a
      public release so every bundled npm/Node dependency is attributed.
- [ ] **Review the top-level `LICENSE.txt`, `SECURITY.md`, and `CONTRIBUTING.md`** for
      project-specific wording so contributors know which license applies to their contributions
      (inbound = outbound, MIT).

## 2. Model and dataset licensing

The shipped generator is a **fine-tuned derivative** of an upstream model, trained on a public
dataset. Both carry attribution obligations that survive quantization.

- [ ] **Apache-2.0 base model.** The release base is
      `Qwen/Qwen2.5-Coder-1.5B-Instruct` (Apache-2.0). Pin the exact upstream commit in
      `docs/MODEL_CARD.md` (replace `<PINNED_REVISION>`), and ship the upstream `LICENSE` **and any
      `NOTICE` file** with the redistributed GGUF. `terramind_ml.merge_sft` writes a `LICENSE`
      naming the base and its license into the merged directory — keep it.
- [ ] **CC-BY-4.0 dataset.** The training corpus is
      [`SASVAAI/terraform-multicloud`](https://huggingface.co/datasets/SASVAAI/terraform-multicloud),
      licensed CC-BY-4.0, pinned at `dced854e79a6aadb89f12b3ba74b31720264ea40`. CC-BY-4.0 requires
      **attribution**: credit the dataset authors and license in the model card and any release
      notes.
- [ ] **Keep `ATTRIBUTION.csv`.** The preparation script (`terramind_ml.sft_data`) writes
      `train.jsonl`, `validation.jsonl`, `ATTRIBUTION.csv`, and `manifest.json`. `ATTRIBUTION.csv`
      records every source repository/license pair. Per-row **source licenses continue to apply**
      to their content, so keep `ATTRIBUTION.csv` and `manifest.json` with any redistributed
      prepared corpus or trained derivative. Review upstream Apache `NOTICE` obligations before
      shipping weights. See [MODEL_CARD.md](MODEL_CARD.md) and
      [GENERATIVE_TRAINING.md](GENERATIVE_TRAINING.md).
- [ ] **Do not bundle non-permissive models.** The default Ollama model `qwen2.5-coder:3b` is under
      the **Qwen Research License (non-commercial)** and must **not** be redistributed inside
      TerraMind or its release assets. The same caution applies to any other model/base whose
      license restricts commercial use or redistribution. Prefer Apache-2.0 bases (for example
      Qwen2.5-Coder-1.5B-Instruct, Qwen3, IBM Granite Code) for anything you ship. Review every
      upstream license before bundling weights. Recorded in
      [MODEL_STRATEGY.md](MODEL_STRATEGY.md).
- [ ] **State the model's limits.** Publish `docs/MODEL_CARD.md` with intended use, out-of-scope
      uses, and the "loss ≠ validity; provider validation required" caveat.

## 3. Hosting the GGUF (release asset, not the git repo)

Model weights are large binaries and must **not** be committed to Git.

- [ ] **Ignore weights.** Add `*.gguf`, `*.safetensors`, and `*.bin` to `.gitignore`
      (`.build/` is already ignored, but a stray `*.gguf` in the working tree is not). Never commit
      a GGUF.
- [ ] **Publish as a GitHub release asset.** Build the artifact with
      `terramind_ml.export_gguf` and attach the quantized `.gguf` to a tagged GitHub Release. Git
      history only holds source and small metadata; release assets hold binaries.
- [ ] **Respect file-size limits.** A `Q4_K_M` build of a 1.5B model is roughly ~1 GB, which fits
      GitHub's **2 GiB per release asset** limit. Repository blobs are warned above 50 MB and hard
      limited at 100 MB, which is another reason not to commit the file. If a build ever exceeds
      the asset limit, use Git LFS or an external host and link it.
- [ ] **Publish the manifest and checksum.** Attach `model-manifest.json` (base model, pinned
      revision, license, quant type, SHA-256, byte size, suggested asset filename) produced by the
      export CLI, and show the SHA-256 in the release notes so users can verify the download.
- [ ] **Name assets predictably.** The export manifest suggests
      `<merged-model>-Q4_K_M.gguf`; keep that name stable across releases and use the same name for
      the manifest.

## 4. How end users run it without their own Ollama

TerraMind's analyzer ships a **bundled GGUF engine** (`app/llama_cpp_backend.py`) built on
`llama-cpp-python` (llama.cpp). Users download the release asset and point TerraMind at it; they
do **not** need to install or run Ollama.

- [ ] **Install the inference runtime.** `llama-cpp-python` is imported lazily and is not part of
      the base analyzer dependencies today, so install it where the analyzer runs:
      `python -m pip install llama-cpp-python` (it builds/vendors llama.cpp for the platform). If
      you want a zero-setup experience, add it to a packaging extra and document that.
- [ ] **Ship or instruct the download.** End users either download the `.gguf` from the GitHub
      Release or the installer fetches it to a local path (for example
      `%LOCALAPPDATA%\TerraMind\models\`). The GGUF stays on the user's machine.
- [ ] **Point TerraMind at the GGUF.** Set the analyzer environment:
      ```powershell
      $env:TERRAMIND_GGUF_MODEL = "C:\path\to\terramind-terraform-Q4_K_M.gguf"
      $env:TERRAMIND_GENERATION_ENGINE = "gguf"   # or leave "auto" to prefer GGUF when set
      ```
      Engine resolution is `gguf` → `transformers` → `ollama` under `auto`; setting
      `TERRAMIND_GGUF_MODEL` makes GGUF the default without touching Ollama.
- [ ] **Tune only if needed.** `TERRAMIND_GGUF_N_CTX` (default 8192), `TERRAMIND_GGUF_TEMPERATURE`
      (0.1), `TERRAMIND_GGUF_MAX_TOKENS` (1024), and `TERRAMIND_GGUF_N_THREADS` bound local
      inference. The analyzer binds to loopback only, so generation stays local.
- [ ] **Keep the human gate.** Generated HCL is parsed and checked, but never applied. Document
      that provider validation (`terramind.analysis.runExternalTools`) and human review are
      required, and that no cost/uptime/security guarantee is implied.

## 5. Copy-paste release checklist

```
[ ] LICENSE.txt (MIT, Microsoft) kept at repo root
[ ] extensions/terramind-core has its own MIT LICENSE
[ ] product.json rebrand retained; no Microsoft trademarks/icons/Marketplace
[ ] ThirdPartyNotices.txt + cglicenses.json regenerated and reviewed
[ ] docs/MODEL_CARD.md updated with base model + pinned revision + license
[ ] docs/MODEL_CARD.md published with loss != validity caveat
[ ] upstream base LICENSE and NOTICE included with the GGUF
[ ] ATTRIBUTION.csv + manifest.json kept with any redistributed corpus/derivative
[ ] no non-permissive model bundled (qwen2.5-coder:3b is non-commercial)
[ ] *.gguf / *.safetensors added to .gitignore; weights never committed
[ ] GGUF + model-manifest.json attached to a tagged GitHub Release
[ ] release notes show the manifest SHA-256
[ ] end-user instructions: download -> TERRAMIND_GGUF_MODEL -> llama-cpp-python, no Ollama
[ ] analyzer loopback-only and human-save gate documented
```

When all boxes are checked, the repository, the extension, and the shipped model each have a clear
license and attribution trail, and users can run TerraMind's generator fully offline with a single
downloaded GGUF file.
