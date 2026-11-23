"""Import user-maintained local files without modifying their originals."""
import hashlib
from pathlib import Path
from office.career import upload_career


def sync_local_files(db, root=None, restore_cv=False):
    root = Path(root) if root else db.path.parent.parent
    notes = []
    with db.connect() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS local_imports (path TEXT PRIMARY KEY, digest TEXT, document_id INTEGER, imported_at TEXT DEFAULT CURRENT_TIMESTAMP)')
    prefs = db.preferences()
    files = [('style', root / 'PUT_YOUR_AI_MODEL_HERE/AI_instructions/writing_style.md'),
             ('preferences', root / 'PUT_YOUR_AI_MODEL_HERE/AI_instructions/job_preferences.md')]
    files += [('cv', p) for p in sorted((root / 'PUT_YOURCV_HERE').glob('*')) if p.is_file() and p.suffix.lower() in {'.pdf', '.docx'}]
    for field, path in files:
        if not path.is_file():
            continue
        try:
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            key = str(path.resolve())
            with db.connect() as conn:
                previous = conn.execute('SELECT digest,document_id FROM local_imports WHERE path=?', (key,)).fetchone()
                missing_cv = field == 'cv' and previous and not conn.execute('SELECT 1 FROM profile_documents WHERE id=?', (previous['document_id'],)).fetchone()
            if previous and previous['digest'] == digest and not (restore_cv and missing_cv):
                continue
            document_id = None
            if field == 'cv':
                document_id = upload_career(db, path.name, content, 'master_cv')
                notes.append(f'CV available for extraction: {path.name}')
            else:
                prefs[field] = content.decode('utf-8-sig')
                db.save_preferences(prefs['style'], prefs['preferences'])
                notes.append(f'Updated {field} from {path.name}')
            with db.connect() as conn:
                conn.execute('INSERT INTO local_imports(path,digest,document_id) VALUES(?,?,?) ON CONFLICT(path) DO UPDATE SET digest=excluded.digest,document_id=excluded.document_id,imported_at=CURRENT_TIMESTAMP', (key, digest, document_id))
        except (ValueError, OSError) as exc:
            notes.append(f'Could not import {path.name}: {exc}')
    return notes
