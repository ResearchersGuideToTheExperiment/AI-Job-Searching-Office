from pathlib import Path
from streamlit.testing.v1 import AppTest
from office.db import Database
from office.control import state


def test_pause_turns_into_enabled_continue(tmp_path,monkeypatch):
    import office.config
    monkeypatch.setattr(office.config,'DATA',tmp_path)
    db=Database(tmp_path/'office.sqlite3')
    with db.connect() as c:
        c.execute("INSERT INTO agent_activity(agent,label) VALUES(2,'Evaluating job suitability')")
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run()
    app.button(key='pause-agent-2').click().run()
    assert not app.exception
    assert state(db)['mode']=='paused'
    button=app.button(key='pause-agent-2')
    assert button.label=='Continue' and not button.disabled
    button.click().run()
    assert state(db)['mode']=='running' and not app.exception
