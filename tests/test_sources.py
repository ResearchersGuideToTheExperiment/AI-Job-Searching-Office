import pytest
from office.discovery import discover
from office.retrieval import Page


def test_candidate_sources_are_separate_from_jobs():
    class Retriever:
        def fetch(self,url):
            return Page(url,b'<a href="/jobs/123">Researcher</a><a href="https://university.example/careers">University careers</a>','text/html')
    result=discover(dict(name='Board',url='https://board.example',pattern=r'/jobs/\d+'),Retriever())
    assert len(result['jobs'])==1
    assert result['suggestions']==[dict(url='https://university.example/careers',name='University careers')]


def test_sources_save_and_invalid_pattern_preserves_file(tmp_path,monkeypatch):
    from office import source_ui,autonomous
    monkeypatch.setattr(source_ui,'DATA',tmp_path)
    monkeypatch.setattr(autonomous,'DATA',tmp_path)
    row=dict(name='Board',url='https://board.example/jobs',pattern=r'/jobs/\d+',enabled=True)
    source_ui.save_sources([row])
    assert autonomous.config().sources==[row]
    with pytest.raises(Exception):source_ui.save_sources([dict(row,pattern='[')])
    assert autonomous.config().sources==[row]
    source_ui.save_sources([])
    assert autonomous.config().sources==[]


def test_automatic_slug_detection_excludes_navigation():
    from office.discovery import automatic_vacancy_link
    base='https://careers.example.org/vacancies'
    assert automatic_vacancy_link(base+'/research-associate-example-city-1234567',base)
    assert not automatic_vacancy_link(base+'?page=2',base)
    assert not automatic_vacancy_link('https://careers.example.org/departments/science',base)
    assert not automatic_vacancy_link('https://other.example/jobs/123',base)


def test_source_needs_only_name_and_url(tmp_path,monkeypatch):
    from office import source_ui,autonomous
    monkeypatch.setattr(source_ui,'DATA',tmp_path)
    monkeypatch.setattr(autonomous,'DATA',tmp_path)
    source_ui.save_sources([dict(name='Example',url='https://careers.example.org/vacancies',enabled=True)])
    assert autonomous.config().sources[0]['pattern']==''
