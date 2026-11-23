# Local AI Job Application Office

I tried online job-search tools and similar local AI job-search systems, but they did not work well for me, so I built my own. It is not perfect, but it got the job done for me. If you would like to improve it or have suggestions, please open an issue or submit a pull request. It worked for my needs at this stage, so I have stopped actively developing it.

A local job-search assistant organized as a small virtual office. Three agents research vacancies, evaluate them against your reviewed profile, and help prepare application documents using a local language model.

You choose the sources, review the evidence, approve drafting, and submit applications yourself. No paid AI API is required.

**Current platform: Windows.** The dashboard uses Streamlit and SQLite; worker locks and process supervision currently depend on Windows APIs. Linux and macOS are not supported yet.

## What it does

- **Research:** discover vacancies from public listing pages or import a job by URL, pasted text, PDF, DOCX, or TXT.
- **Evaluation:** extract requirements with source quotes and compare them against confirmed CV facts.
- **Preparation:** produce editable DOCX drafts and a checklist after you approve an evaluation.
- **Review:** track decisions, deadlines, document versions, and manually submitted applications.
- **Local inference:** use Ollama on your own machine. Job discovery still requires internet access.

<img width="574" height="1472" alt="image" src="https://github.com/user-attachments/assets/9e777a0b-99f6-406a-a430-8b77db0fa7f2" />

This is an experimental personal tool. Review extracted facts, eligibility, deadlines, and documents before using them. A match score measures evidence coverage, not hiring probability.

## Suggested setup (Windows Command Prompt or PowerShell)

1. Download and install [Python 3.14 for Windows](https://www.python.org/downloads/windows/). Include the Python launcher if the installer offers it. Python 3.14.3 is the version used for local validation.
2. Download and install [Ollama for Windows](https://ollama.com/download/windows), then open Ollama. **Ollama** is the program that runs the AI model; this project's suggested minimum model is **Qwen3 8B**. (note that I used this model but more powerful version would surely give better results) You do not need a paid API account or a separate Llama download.
3. Download this repository using **Code → Download ZIP** on GitHub and extract it, or clone it with Git.
4. Open the extracted project folder in File Explorer. Click the address bar, type `cmd`, and press Enter. This opens Command Prompt in the correct folder. PowerShell also works.

Run the commands below **in that terminal**, one line at a time, not inside an Ollama chat. After installing Python or Ollama, reopen the terminal if their commands are not recognized. The [Ollama Windows guide](https://docs.ollama.com/windows) covers installation troubleshooting.

### 1. Install Python dependencies

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Activation is unnecessary. The tested dependency snapshot is in `requirements.lock.txt`; use `requirements.txt` for the normal installation.

### 2. Set up the local model

With Ollama running, download and register the suggested model:

```powershell
ollama pull qwen3:8b
ollama create qwen3-office -f Modelfile
ollama list
```

The included Modelfile creates the name expected by the app with an 8,192-token context window. The [Qwen3 8B model](https://ollama.com/library/qwen3:8b) download is approximately 5.2 GB; running it requires additional memory. Performance depends on your CPU/GPU and available memory. Model weights are downloaded separately and are not included in this repository.

**Where the model goes:** with `ollama pull`, Ollama manages storage itself, so you can leave `PUT_YOUR_AI_MODEL_HERE/` empty. If you already downloaded a compatible Qwen3 8B GGUF, put it in that folder as `model.gguf` and use this command **instead of** the pull/create commands above:

```bat
ollama create qwen3-office -f PUT_YOUR_AI_MODEL_HERE\Modelfile
```

See the [model folder guide](PUT_YOUR_AI_MODEL_HERE/README.md) and [configuration](docs/CONFIGURATION.md). Model setup follows the [Ollama Modelfile reference](https://docs.ollama.com/modelfile).

### 3. Add your CV

Put your PDF or DOCX CV directly in **`PUT_YOURCV_HERE/`**. The folder is included in the download and contains an instruction file. You can also upload a CV through the dashboard instead. Your actual CV is ignored by Git and excluded from source releases.

### 4. Launch

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Open [the local dashboard](http://127.0.0.1:8501). Alternatively, run `launch.ps1` from PowerShell or double-click `Start Job Office.bat` after setup.

Keep the server window open. Ctrl+C stops the dashboard; closing its process stops its child office workers. The independently installed Ollama service remains running. Automatic login and scheduled startup are disabled.

## Make it your own

A fresh installation has **no CV, profile facts, jobs, saved preferences, target countries, or configured sources**. Its time zone defaults to UTC.
<img width="568" height="644" alt="image" src="https://github.com/user-attachments/assets/814b62e4-277a-4ccf-824d-0a44d6f15862" />

1. **Settings:** test the local Ollama connection. Defaults are `http://localhost:11434` and `qwen3-office`.
2. **My Profile:** your folder CV appears under **Original CV and supporting materials**. Choose **Extract / retry**, or upload a CV through the page. Correct mistakes and select **Confirm all reviewed information**. Only confirmed facts support evaluations and drafts.
3. **My Profile:** enter your writing style and application preferences. Optional file templates are in [examples](examples/README.md); they are never imported automatically.
4. **Autonomous Office → Office configuration:** set your time zone, target countries, recommendation threshold, and whether to include PhD studentships. Empty countries mean no country preference.
5. **Sources:** add the public job-listing pages you want searched. Discovery starts without any sources; manual job import works without them.
6. **Add Job** or start research from the office controls. Review the extracted advertisement and suitability evaluation in **Job Processing**.
7. **Approve and start preparation** for a suitable job. Review and edit the generated documents in **Applications**, submit them yourself, then mark the application as applied.

Long documents can require several sequential model calls. Pause and Stop take effect at checkpoints, so an in-flight model request may finish first. Resume continues pending work. Completed work is retained.

## Privacy and storage

CVs, preferences, job history, original uploads, model responses, and application drafts are stored locally and **are not encrypted by this app**.

| Location | Contents |
| --- | --- |
| `data/office.sqlite3` | Profile, original uploads, jobs, evaluations, preferences, decisions, history |
| `data/applications/` | Generated application documents |
| `data/settings.json` | Local model connection settings |
| `data/autonomous.json` | Search sources and office settings |
| `PUT_YOURCV_HERE/` | Optional PDF/DOCX files for local import |
| `PUT_YOUR_AI_MODEL_HERE/` | Optional manually downloaded GGUF model |
| `PUT_YOUR_AI_MODEL_HERE/AI_instructions/` | Optional personal preference Markdown files |

Private contents in these locations are ignored by Git and excluded from the release exporter. Only the two folder guides and the model folder's bundled Modelfile are public. Keep those guide files free of personal details. Inspect staged changes before pushing. Do not upload the whole working folder as an archive: use the [publication workflow](docs/PUBLISHING.md).

The app sends inference requests to a loopback Ollama endpoint. Public job retrieval does not attach your CV/profile to website requests. Public websites still see ordinary network requests and your IP address. Streamlit usage statistics are disabled, and the dashboard binds to loopback. This is a single-user local app, without remote-user authentication.

See [privacy and cleanup](docs/PRIVACY.md) for backups, deletion, and publication checks.

## Limits

- Discovery reads accessible HTML listing pages; it is not a general web search engine and does not guarantee complete coverage. Website changes can break recognition.
- Login-only, JavaScript-only, CAPTCHA-protected, or blocked adverts require manual paste/upload. Retrieval does not bypass access restrictions.
- CVs: DOCX or text-based PDF. Supporting materials: PDF, DOCX, UTF-8 TXT. Uploads are limited to 10 MB; PDFs to 100 pages. OCR is not implemented.
- Drafts use confirmed facts and conservative composition. Extraction and matching can still be incomplete or wrong.
- Certificates, transcripts, references, and other official documents remain manual tasks. Review document limits and final formatting yourself.
- No account creation, portal form filling, email sending, or automatic submission is implemented.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/check_server.py
.\.venv\Scripts\python.exe scripts/build_release.py --check
```

Tests use fictional fixtures and mocked model/network responses. The HTTP smoke check starts and stops a separate dashboard. An optional model smoke test is documented in [CONTRIBUTING.md](CONTRIBUTING.md).

The source is organized in `office/`: discovery/retrieval, profile extraction, evidence evaluation, document preparation, persistence, and Streamlit views. See [configuration](docs/CONFIGURATION.md), [contributing](CONTRIBUTING.md), [validation results](docs/VALIDATION.md), and [publication instructions](docs/PUBLISHING.md).

## License

Project code is available under the [MIT License](LICENSE), allowing personal and commercial reuse with the license notice retained. Model weights and third-party dependencies have their own licenses; the project's MIT license does not relicense them. See [third-party notices](THIRD_PARTY_NOTICES.md).

