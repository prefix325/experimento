# Online preparation

Status: `DEVELOPMENT_ONLY`.

Run from an elevated PowerShell only during the connected preparation phase:

```powershell
Set-Location X:\PSQZA_TEP_LOCAL\repo
.\scripts\prepare_online.ps1
```

The script verifies WSL2, Docker and NVIDIA; builds the image from a pinned
`llama.cpp` CUDA digest; runs unit and GPU tests; separates blind detector data
from ground truth; downloads the explicitly documented provisional GGUF model;
and writes machine- and human-readable preparation manifests under
`X:\PSQZA_TEP_LOCAL\manifests`.

The model and datasets remain outside Git. They are not copied into the image.
The source GitHub Actions artifact is retained separately under
`data/source_artifact_31752037426` and is never mounted in detector runs because
its CSV files contain `y`.

Smoke and pilot values are provisional engineering settings. Do not use their
outputs for scientific inference or parameter optimization.
