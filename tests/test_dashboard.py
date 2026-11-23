from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_dashboard_pages(tmp_path, monkeypatch):
    import office.config
    monkeypatch.setattr(office.config, 'DATA', tmp_path)
    from office.db import Database
    Database(tmp_path / 'office.sqlite3').add_job('Example research advertisement')
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
    assert not app.exception
    expected = ['Autonomous Office', 'My Profile', 'Sources', 'Add Job', 'Job Processing', 'Applications', 'Settings']
    assert app.sidebar.radio[0].options == expected
    for page in expected[1:]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page
    for section in ['Data Management', 'Application History']:
        next(r for r in app.radio if r.label == 'Settings section').set_value(section).run()
        assert not app.exception, section


def test_checklist_completion_survives_new_session(tmp_path, monkeypatch):
    import office.config
    from office.db import Database
    monkeypatch.setattr(office.config, 'DATA', tmp_path)
    db = Database(tmp_path / 'office.sqlite3')
    from test_application_ui import application_fixture
    job_id = application_fixture(db)
    path = str(Path(__file__).resolve().parents[1] / 'app.py')
    app = AppTest.from_file(path).run()
    app.sidebar.radio[0].set_value('Applications').run()
    app.checkbox[0].check().run()
    assert not app.exception
    assert next(task for task in db.tasks(job_id) if 'Upload a CV' in task['text'])['complete'] == 1
    other = AppTest.from_file(path).run()
    other.sidebar.radio[0].set_value('Applications').run()
    assert other.checkbox[0].value is True
