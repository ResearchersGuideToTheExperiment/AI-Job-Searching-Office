from office.db import Database


def test_duplicate_cv_facts_review_once(tmp_path):
    db = Database(tmp_path / 'db')
    for name in ['first.pdf', 'second.docx']:
        doc = db.add_profile_document(name, name.encode(), 'Alex Example', 'master_cv')
        db.save_extracted_facts(doc, [{'category':'identity','text':'Alex Example','source_quote':'Alex Example'}])
    facts = db.facts()
    assert len(facts) == 1
    db.confirm_fact_review([{'ID':facts[0]['id'],'Fact':'Alex Corrected','Category':'identity','Incorrect':True}], facts)
    assert len(db.facts(True)) == 1
    assert db.facts()[0]['text'] == 'Alex Corrected'
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM profile_facts WHERE text=?', ('Alex Corrected',)).fetchone()[0] == 2
    facts = db.facts()
    db.confirm_fact_review([{'ID':facts[0]['id'],'Fact':'Alex Corrected','Category':'identity','Incorrect':True}], facts)
    assert not db.facts(True)
