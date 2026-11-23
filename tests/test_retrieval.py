import socket
import pytest
from office.retrieval import public_target, PublicRetriever, RetrievalError, Page, import_url
from office.db import Database


@pytest.mark.parametrize('url', ['file:///etc/passwd','http://localhost','http://127.0.0.1','http://10.0.0.1', 'http://169.254.169.254','http://[::1]', 'http://user:pass@example.org', 'ftp://example.org', 'http://example.org:8080'])
def test_reject_unsafe_targets(url, monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [(2,1,6,'',('127.0.0.1',80))])
    with pytest.raises(RetrievalError):
        public_target(url)


def test_redirect_and_robots(monkeypatch):
    import office.retrieval as module
    calls = []
    def target(url):
        calls.append(url)
        if '127.0.0.1' in url:
            raise RetrievalError('private')
        return None
    monkeypatch.setattr(module, 'public_target', target)
    fetcher = PublicRetriever()
    monkeypatch.setattr(fetcher, '_allowed', lambda url: None)
    monkeypatch.setattr(fetcher, '_once', lambda url: (302, {'Location':'http://127.0.0.1'}, b''))
    with pytest.raises(RetrievalError, match='private'):
        fetcher.fetch('https://example.org/ad')
    assert len(calls) == 2
    robots = PublicRetriever()
    monkeypatch.setattr(robots, '_once', lambda url: (200, {}, b'User-agent: *\nDisallow: /'))
    with pytest.raises(RetrievalError, match='disallows'):
        robots._allowed('https://example.org/ad')


def test_import_preserves_sources(tmp_path):
    html = b'<html><title>University research vacancy</title><body><h1>Research Associate</h1><p>Applicants must hold a PhD in psychology. Experience with visual perception experiments and participant testing is essential. Upload a CV and cover letter.</p><a href="https://example.org/apply">Apply here</a><a href="/blocked.pdf">Job description PDF</a></body></html>'
    class FixtureRetriever:
        def fetch(self, url):
            if url.endswith('.pdf'):
                raise RetrievalError('HTTP 403')
            return Page(url, html, 'text/html')
    db = Database(tmp_path / 'db')
    job_id, warnings = import_url(db, 'https://example.org/job', FixtureRetriever())
    assert 'https://example.org/apply' in db.job(job_id)['original']
    assert db.sources(job_id)[0]['content'] == html
    assert db.sources(job_id)[0]['retrieved_at']
    assert '403' in warnings[0]


def test_linked_pdf_is_retrieved_and_preserved(tmp_path):
    from test_core import synthetic_pdf
    pdf_bytes = synthetic_pdf('A 500-word supporting statement is required.')
    html = b'<html><body><h1>Research Associate</h1><p>A university research position with detailed application requirements. Please consult the linked person specification before preparing your application.</p><a href="/person.pdf">Person specification PDF</a></body></html>'
    class Fixture:
        def fetch(self, url):
            return Page(url, pdf_bytes, 'application/pdf') if url.endswith('.pdf') else Page(url, html, 'text/html')
    db = Database(tmp_path / 'db')
    job, notices = import_url(db, 'https://example.org/job', Fixture())
    assert not notices
    assert '500-word supporting statement' in db.job(job)['original']
    assert db.sources(job)[1]['content'] == pdf_bytes


def test_socket_uses_validated_ip_and_tls_hostname(monkeypatch):
    import office.retrieval as module
    captured = {}
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [(2,1,6,'',('93.184.215.14',443))])
    class Response:
        status = 200
        headers = {'Content-Type':'text/html'}
        def stream(self, *args, **kwargs):
            yield b'ok'
        def close(self):
            pass
    class Pool:
        def __init__(self, host, port, **kwargs):
            captured.update(host=host, port=port, **kwargs)
        def urlopen(self, method, path, **kwargs):
            captured['request'] = kwargs
            return Response()
        def close(self):
            pass
    monkeypatch.setattr(module.urllib3, 'HTTPSConnectionPool', Pool)
    PublicRetriever()._once('https://example.org/job')
    assert captured['host'] == '93.184.215.14'
    assert captured['server_hostname'] == 'example.org'
    assert captured['assert_hostname'] == 'example.org'
    assert captured['request']['redirect'] is False
