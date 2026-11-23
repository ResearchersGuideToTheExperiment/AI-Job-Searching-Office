# Privacy and cleanup

The release contains code, documentation, and fictional examples. Personal documents, saved databases, generated application files, preferences, logs, captured job adverts, and historical investigation reports are not part of the release.

## Local use

The database stores original uploaded bytes as well as extracted text, profile facts, model responses, preferences, decisions, and application history. Application documents also exist separately under `data/applications/`. Files are local and unencrypted. Protect the computer and any backups accordingly.

Stop the dashboard and its workers before copying a backup. Back up the entire `data/` directory, together with any original documents and optional preference files you need. Keep backups outside the repository.

**Settings → Data Management** supports selective deletion after the office is stopped. Removing profile records does not remove original CV files. Clearing preferences does not remove Markdown preference sources. Some deletion actions retain generated documents unless their removal is explicitly selected. This is application cleanup, not secure disk erasure.

For a completely fresh local setup, stop all project processes, then remove your private `data/`, `PUT_YOURCV_HERE/`, and `PUT_YOUR_AI_MODEL_HERE/AI_instructions/` contents. The app creates a new database on its next launch. Keep model weights if you want to reuse them.

Keep the public README guides and bundled Modelfile when clearing personal files from the two PUT_YOUR folders.

## Publishing

Git ignore rules prevent ordinary staging of common private paths. They do not remove content already committed, prevent force-adds, or sanitize screenshots, issue attachments, or Git author metadata.

Use `scripts/build_release.py` to export only paths listed in `PUBLIC_FILES.txt`. It rejects unexpected file types, private directories, symbolic links, and several common secret/machine-path patterns. The only exceptions inside the two PUT_YOUR folders are their public README guides and `PUT_YOUR_AI_MODEL_HERE/Modelfile`. Keep these three files free of personal information. This is a guardrail, not a guarantee that arbitrary edited source contains no personal data.

Review every file intended for publication. If you add a new public source file, add its exact path to the manifest after review. Never add private documents or generated data to that manifest.

A fresh exported archive contains no `.git` directory or old commit history. If you publish from an existing repository that previously contained sensitive files, deleting them in a new commit does not remove historical copies. Review that history before publication. The exporter deliberately does not copy it.

Use fictional profiles in bug reports. Logs, model responses, filenames, and screenshots can reveal private details even when credentials are absent.

