# Contributing

Use Windows and follow the README setup instructions. Run the automated checks before submitting a change:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/check_server.py
.\.venv\Scripts\python.exe scripts/build_release.py --check
```

Tests mock external model/network responses and use temporary databases. Preserve explicit fact review, evaluation approval before drafting, source isolation, and manual submission. Include a focused regression test for changes to those boundaries.

Use fictional CVs and advertisements. Do not commit private inputs, model weights, real application history, or captured websites containing personal information. Inspect diffs and attachments before sharing.

An optional integration check uses a running local Ollama model and fictional inputs:

```powershell
.\.venv\Scripts\python.exe scripts/extended_smoke.py
```

It can take several minutes and writes ignored artifacts under `data/synthetic-validation/`. To test public retrieval as well, pass `--probe-url` with an accessible vacancy URL. `scripts/probe_discovery.py` contacts only your configured enabled sources and records results under `data/`.

If you add public files, review them and add their exact relative paths to `PUBLIC_FILES.txt`. The exporter intentionally omits unlisted files. The dependency snapshot reflects a development environment, not bundled third-party code.

For a pull request, explain the problem, resulting behavior, and checks performed. Contributions to this project's code are provided under its MIT license.

