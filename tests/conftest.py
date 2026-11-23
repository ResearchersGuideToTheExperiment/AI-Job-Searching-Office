import pytest


@pytest.fixture(autouse=True)
def isolated_inference_lock(tmp_path,monkeypatch):
    # Mocked AI tests must not contend with the user's actual background model.
    import office.inference_lock
    monkeypatch.setattr(office.inference_lock,'DATA',tmp_path)
    import office.case_worker
    monkeypatch.setattr(office.case_worker,'ensure_worker',lambda db:None)
