import pytest
from office.db import Database
from streamlit.testing.v1 import AppTest
from pathlib import Path


def review_rows(facts):
    return [{'ID': f['id'], 'Fact': f['text'], 'Category': f['category'], 'Incorrect': False} for f in facts]


def test_bulk_confirm_correct_and_exclude(tmp_path):
    db = Database(tmp_path / 'db')
    for text in ['Correct fact', 'Wrong fact', 'Needs correction']:
        db.save_fact(None, 'research', text, False)
    facts = db.facts()
    rows = review_rows(facts)
    rows[1]['Incorrect'] = True
    rows[2].update(Incorrect=True, Fact='Corrected fact')
    assert db.confirm_fact_review(rows, facts) == (2, 1)
    loaded = Database(db.path).facts()
    assert [f['confirmed'] for f in loaded] == [1, 0, 1]
    assert loaded[2]['text'] == 'Corrected fact'


def test_invalid_or_stale_bulk_review_is_atomic(tmp_path):
    db = Database(tmp_path / 'db')
    db.save_fact(None, 'skills', 'First', False)
    db.save_fact(None, 'skills', 'Second', False)
    facts = db.facts()
    rows = review_rows(facts)
    rows[1]['Fact'] = ''
    with pytest.raises(ValueError):
        db.confirm_fact_review(rows, facts)
    assert not db.facts(True)
    db.save_fact(facts[1]['id'], 'skills', 'Changed elsewhere', False)
    with pytest.raises(ValueError, match='another session'):
        db.confirm_fact_review(review_rows(facts), facts)
    assert not db.facts(True)


def test_profile_table_single_confirmation(tmp_path, monkeypatch):
    import office.config
    monkeypatch.setattr(office.config, 'DATA', tmp_path)
    db = Database(tmp_path / 'office.sqlite3')
    document = db.add_profile_document('synthetic.txt', b'Synthetic skill', 'Synthetic skill', 'master_cv')
    db.save_extracted_facts(document, [{'category':'skills', 'text':'Synthetic skill', 'source_quote':'Synthetic skill'}])
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
    app.sidebar.radio[0].set_value('My Profile').run()
    assert not app.exception
    assert not db.facts(True)
    buttons = [b for b in app.button if b.label == 'Confirm all reviewed information']
    assert len(buttons) == 1
    buttons[0].click().run()
    assert not app.exception
    assert len(db.facts(True)) == 1
