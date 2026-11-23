from office.db import Database
from office.local_files import sync_local_files
from test_profile import synthetic_cv


def test_remove_document_keeps_other_sources_and_disk_file(tmp_path):
    folder = tmp_path / 'PUT_YOURCV_HERE'
    folder.mkdir()
    path = folder / 'master.docx'
    path.write_bytes(synthetic_cv())
    db = Database(tmp_path / 'data/office.sqlite3')
    sync_local_files(db)
    first = db.profile_documents()[0]['id']
    second = db.add_profile_document('other.txt', b'Other', 'Other', 'other')
    for doc in (first, second):
        db.save_extracted_facts(doc, [{'category':'identity','text':'Example','source_quote':'Example'}])
    db.remove_profile_document(first)
    assert path.exists()
    assert [d['id'] for d in db.profile_documents()] == [second]
    assert db.facts()[0]['document_id'] == second
    assert sync_local_files(db) == []
    assert len(db.profile_documents()) == 1
    notes = sync_local_files(db, restore_cv=True)
    assert len(notes) == 1
    assert len(db.profile_documents()) == 2
    assert sync_local_files(db, restore_cv=True) == []
