# Configuration

## Inference

Settings accepts only local HTTP Ollama URLs, such as `http://localhost:11434`. The default installed model name is `qwen3-office`. The UI lets you save a different local model name and timeout (30–900 seconds). Model requests use structured JSON output, non-thinking mode, and an 8,192-token context window; alternative models may need testing.

The root Modelfile uses `FROM qwen3:8b` for the Ollama download workflow. The supplied `PUT_YOUR_AI_MODEL_HERE/Modelfile` supports a local GGUF and contains:

```text
FROM ./model.gguf
PARAMETER num_ctx 8192
```

Place your compatible GGUF at `PUT_YOUR_AI_MODEL_HERE/model.gguf`, then run:

```powershell
ollama create qwen3-office -f PUT_YOUR_AI_MODEL_HERE/Modelfile
```

Relative GGUF paths resolve from the Modelfile's directory. The template is public; keep machine-specific paths out of committed changes. The GGUF itself stays private and is excluded from releases. See the [official reference](https://docs.ollama.com/modelfile).

## Profile and preferences

Upload through **My Profile**, or create `PUT_YOURCV_HERE/` and put PDF/DOCX CVs there. Local imports preserve originals and avoid duplicate file content. Extract the document, review all facts, then confirm them. Importing alone does not establish qualifications.

Optional preference files:

- `PUT_YOUR_AI_MODEL_HERE/AI_instructions/job_preferences.md`
- `PUT_YOUR_AI_MODEL_HERE/AI_instructions/writing_style.md`

Copy the corresponding files from `examples/`, then replace the placeholders before launching. A changed file synchronizes to the database on a dashboard rerun. UI edits persist until that source file changes; UI saves do not modify the Markdown files.

Preferences guide relevance, but do not invent qualifications or redefine the scoring formula. Essential/eligibility criteria have weight 2; preferred/desirable criteria weight 1. Satisfied = 1, partial = 0.5, not satisfied or unknown = 0. Unknown is not proof of failure.

## Sources and office settings

No sources or target countries are preselected. Add public listing URLs on **Sources** and choose countries/time zone in **Autonomous Office → Office configuration**.

Source configuration is stored in `data/autonomous.json`. A fictional source schema is included in `examples/autonomous.example.json`; its source is disabled and must be replaced with a real listing URL. It is documentation, not an automatic configuration import.

Sources normally need only a name and URL. Advanced users can set an optional `pattern` regular expression in the JSON to identify vacancy links. Avoid overly broad patterns that also match navigation. Candidate sources discovered by the app require your approval before they become search sources.

Defaults: UTC, no country filter, recommendation threshold 85, maximum five preparation attempts per run, PhD studentships excluded. Drafting always requires approval of the current evaluation, including when a score exceeds the threshold. Profile or requirement changes invalidate old approvals. Legacy `time` fields do not enable scheduling.

## Data directory

By default, all runtime data lives in `data/`. To relocate it, set the environment variable before launch:

```powershell
$env:JOB_OFFICE_DATA_DIR = Join-Path $PWD 'data'
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Use an absolute path for a custom directory. Local CV/preference synchronization looks for `PUT_YOURCV_HERE/` and `PUT_YOUR_AI_MODEL_HERE/AI_instructions/` beside the data directory (in its parent). Those private paths must also be excluded from any repository or backup you share.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Cannot reach Ollama | Start Ollama; check the local URL and installed model in Settings. |
| Model is missing | Run the pull/create commands in the README, then inspect `ollama list`. |
| No discoveries | Add and enable sources; inspect their status. Try importing a vacancy directly. |
| No confirmed facts | Extract the CV, review the fact table, then confirm it. |
| Preparation is waiting | Approve the latest evaluation and check Pause/Stop state. |
| Invalid or truncated AI response | Retry; long input may need a smaller manual import or a more capable local model. |
| Port 8501 is busy | Stop the previous dashboard before launching another. Run one office per data directory. |
| PowerShell blocks launch.ps1 | Use the explicit Python launch command from the README. |

