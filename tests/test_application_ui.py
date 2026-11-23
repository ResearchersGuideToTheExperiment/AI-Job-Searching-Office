import json
from pathlib import Path

import pytest
from docx import Document
from streamlit.testing.v1 import AppTest

from office.application_ui import motivation_item, save_letter
from office.career import profile_fingerprint
from office.config import Settings
from office.coordinator import build_tasks
from office.db import Database
from office.decisions import save_decision
from office.documents import plan_documents, prepare_package, save_version
from office.evaluation import analysis_fingerprint
from office.models import Analysis, Fact, Requirement, FACT_FIELDS
from office.navigation import selected_jobs


def application_fixture(db, *, letter=True, embedded=False):
    original = ('Research fellow studying vision and virtual reality. A PhD is essential. '
                'Experience with VR is required; Python and animal research are preferred. '
                'Upload a CV, two references and an experiment proposal. Apply by 30 November 2026.')
    job = db.add_job(original, 'https://example.org/vision-job')
    fact = db.save_fact(None, 'research', 'Completed a PhD studying vision using virtual reality.', True)
    analysis = Analysis(**{field: Fact(value=None, source_quote=None) for field in FACT_FIELDS}, requirements=[])
    analysis.title = Fact(value='Vision Research Fellow', source_quote='Vision Research Fellow')
    analysis.deadline = Fact(value='30 November 2026', source_quote='30 November 2026')
    rows = [('essential', 'PhD required.', 'satisfied'), ('essential', 'VR experience required.', 'satisfied'),
            ('desirable', 'Python experience preferred.', 'partial'),
            ('desirable', 'Animal research experience preferred.', 'unknown')]
    for category, text, _ in rows:
        analysis.requirements.append(Requirement(category=category, text=text, source_quote=text, importance='mandatory'))
    for category, text in [('document', 'Upload a CV.'), ('document', 'Provide two references.'),
                           ('document', 'Provide an experiment proposal (maximum 500 words).'),
                           ('question', 'Describe a relevant experiment.')]:
        analysis.requirements.append(Requirement(category=category, text=text, source_quote=text, importance='mandatory'))
    if letter:
        text = 'Upload a supporting statement.' if embedded else 'Upload a motivation letter (maximum 300 words).'
        source = 'Upload a supporting statement including a cover letter.' if embedded else text
        analysis.requirements.append(Requirement(category='document', text=text, source_quote=source, importance='mandatory'))
    run = db.start_run(job, Settings(), 'fixture')
    db.save_analysis(job, analysis, [], build_tasks(analysis, []), run, '{}')
    payload = {'score': 75, 'criteria': [
        {'criterion': text, 'result': result, 'category': category, 'importance': 'mandatory',
         'explanation': 'Partial evidence.' if result == 'partial' else 'No confirmed evidence.' if result == 'unknown' else 'Confirmed.',
         'evidence': [{'fact_id': fact, 'quote': db.facts(True)[0]['text']}] if result == 'satisfied' else []}
        for category, text, result in rows]}
    evaluation_id = db.save_evaluation(job, profile_fingerprint(db.facts(True)), analysis_fingerprint(analysis), payload)
    save_decision(db, job, evaluation_id, 75, 'approved')
    prepare_package(db, job)
    item = motivation_item(plan_documents(analysis))
    if item:
        save_version(db, db.package(job), item, 'Dear committee,\n\nMy research focuses on vision and virtual reality.', [], [], 'Fixture')
    return job


def open_app(tmp_path, monkeypatch, *, letter=True, embedded=False):
    import office.config
    import office.local_files
    monkeypatch.setattr(office.config, 'DATA', tmp_path)
    monkeypatch.setattr(office.local_files, 'sync_local_files', lambda db: [])
    db = Database(tmp_path / 'office.sqlite3')
    job = application_fixture(db, letter=letter, embedded=embedded)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
    app.sidebar.radio[0].set_value('Applications').run()
    assert not app.exception
    return app, db, job


def test_combined_application_layout_and_evidence(tmp_path, monkeypatch):
    app, _, _ = open_app(tmp_path, monkeypatch)
    assert 'Application Checklist' not in app.sidebar.radio[0].options
    assert 'Application Package' not in app.sidebar.radio[0].options
    assert app.main.selectbox[0].label == 'Select a saved job'
    assert app.main.metric[0].label == 'Deadline to apply'
    assert app.main.metric[0].value == '30 November 2026'
    panels = app.main.get('expander')
    assert [panel.label for panel in panels] == ['Original job post', 'My strengths', 'Gaps and shortcomings', 'Motivation letter']
    assert all(panel.proto.expanded for panel in panels)
    strengths, gaps = panels[1:3]
    assert any('PhD required' in item.value for item in strengths.caption)
    assert any('VR experience' in item.value for item in strengths.caption)
    assert any('Confirmed.' in item.value for item in strengths.markdown)
    assert not any('Your CV:' in item.value for panel in (strengths, gaps) for item in panel.caption)
    assert any('Partial match' in item.value for item in gaps.caption)
    assert any('Not evidenced in your CV' in item.value for item in gaps.caption)
    assert [item.label for item in app.main.text_area] == ['Motivation letter text']
    assert not any(item.value in {'Application answer', 'Supporting statement'} for item in app.subheader)
    assert any('two references' in item.label for item in app.checkbox)
    assert any('experiment proposal' in item.label for item in app.checkbox)
    assert app.main.button[-1].label == 'Applied'


@pytest.mark.parametrize('letter,embedded', [(False, False), (True, True)])
def test_only_requested_letter_has_an_editor(tmp_path, monkeypatch, letter, embedded):
    app, _, _ = open_app(tmp_path, monkeypatch, letter=letter, embedded=embedded)
    assert bool(app.main.text_area) is letter
    assert ('Motivation letter' in [panel.label for panel in app.main.get('expander')]) is letter


def test_letter_edit_saves_a_new_version_and_persists(tmp_path, monkeypatch):
    app, db, job = open_app(tmp_path, monkeypatch)
    text = 'Dear committee,\n\nI am applying for the Vision Research Fellow position.'
    app.main.text_area[0].set_value(text)
    next(button for button in app.button if button.label == 'Save motivation letter').click().run()
    assert not app.exception
    drafts = db.drafts(db.package(job)['id'])
    assert len(drafts) == 2
    assert drafts[0]['body'] == text and drafts[0]['version'] == 2
    assert json.loads(drafts[0]['evidence']) == []
    assert text in '\n\n'.join(p.text for p in Document(drafts[0]['file_path']).paragraphs)
    assert app.main.text_area[0].value == text
    other = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
    other.sidebar.radio[0].set_value('Applications').run()
    assert not other.exception and other.main.text_area[0].value == text


def test_applied_archives_without_removing_the_job_or_documents(tmp_path, monkeypatch):
    app, db, job = open_app(tmp_path, monkeypatch)
    package = db.package(job)
    app.button(key=f'application-applied-{job}').click().run()
    assert not app.exception
    assert db.job(job)['status'] == 'Submitted manually'
    assert not selected_jobs(db)
    assert db.drafts(package['id']) and Path(db.drafts(package['id'])[0]['file_path']).is_file()
    assert any('Marked as applied' in item.value for item in app.success)


def test_letter_save_rejects_stale_approval_and_length_overflow(tmp_path):
    db = Database(tmp_path / 'office.sqlite3')
    job = application_fixture(db)
    item = motivation_item(json.loads(db.package(job)['plan']))
    evaluation_id = db.evaluation(job)['id']
    with pytest.raises(ValueError, match='Over word limit'):
        save_letter(db, job, item['key'], 'word ' * 301, evaluation_id)
    db.save_fact(None, 'skills', 'Python', True)
    with pytest.raises(ValueError, match='Approve'):
        save_letter(db, job, item['key'], 'Updated letter.', evaluation_id)
    assert len(db.drafts(db.package(job)['id'])) == 1
