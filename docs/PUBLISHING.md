# Publishing on GitHub

## Prepare the release

Run from the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/build_release.py --check
.\.venv\Scripts\python.exe scripts/build_release.py
```

The exporter uses only the reviewed paths in `PUBLIC_FILES.txt` and writes `dist/local-ai-job-office-source.zip`. It excludes runtime data, CVs, private instructions, model weights, virtual environments, caches, logs, and Git history. It uses standard Python only, so `py -3.14 scripts/build_release.py` also works before installing dependencies.

Extract this archive to a **new folder**. Review its contents, README, license, and example files. Publish from the extracted folder. Do not upload an archive made from the entire working directory.

## Create the repository

Suggested repository name: `local-ai-job-office`.

Suggested GitHub description:

> A local AI job-search office for vacancy discovery, evidence-based matching, and application drafting with Ollama. Review and submit applications yourself.

Suggested topics: `ollama`, `local-ai`, `job-search`, `streamlit`, `python`, `application-assistant`.

Create an empty repository on GitHub. The exported project already includes a README, MIT LICENSE, and .gitignore, so do not generate additional ones during creation.

The README already includes the author's introduction and maintenance status. GitHub displays it on the repository home page automatically; no separate GitHub Pages website is needed.

From the extracted folder:

```powershell
git init -b main
git config user.name
git config user.email
git add .
git status --short
git diff --cached --stat
git diff --cached
```

The two config commands display the identity that will be recorded in commits. Set a preferred public name and a GitHub-provided no-reply email in repository-local Git configuration if desired.

After reviewing the staged content, commit and push. Replace the remote placeholder below with your repository URL:

```powershell
git commit -m "Initial open-source release"
git remote add origin https://github.com/YOUR-ACCOUNT/local-ai-job-office.git
git push -u origin main
```

You can alternatively upload the extracted files through GitHub's web interface; ensure hidden files and folders such as `.gitignore`, `.streamlit/`, and `.github/` are included. No repository has been created or pushed by the cleanup workflow itself.

## After publication

The included GitHub Actions workflow runs tests on Windows and checks the release manifest. Review its first run; local validation is not proof of a clean dependency installation on a new machine.

Keep future personal inputs in ignored private directories. Review diffs before each push and rerun the exporter when preparing release archives. Avoid using real application records in screenshots or examples.

