"""Bounded public HTTP GETs with DNS pinning, redirect checks and robots policy."""
from dataclasses import dataclass,field
import ipaddress
import socket
import time
from urllib.parse import urlsplit, urlunsplit, urljoin
from urllib.robotparser import RobotFileParser
import certifi
import urllib3
from bs4 import BeautifulSoup
import trafilatura
from office.ingest import read_upload, MAX_BYTES
from office.advertisement import clean_html,assert_target

USER_AGENT = 'LocalJobOffice/2.0'


class RetrievalError(ValueError):
    pass


def public_target(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password
                or parts.port not in {None, 80, 443} or any(ord(c) < 33 for c in url) or '\\' in url):
            raise RetrievalError('Only public HTTP/HTTPS URLs on standard ports without credentials are allowed.')
        host = parts.hostname.encode('idna').decode('ascii')
        addresses = {a[4][0] for a in socket.getaddrinfo(host, parts.port or (443 if parts.scheme == 'https' else 80), type=socket.SOCK_STREAM)}
        if not addresses:
            raise RetrievalError('No address found for this host.')
        for address in addresses:
            ip = ipaddress.ip_address(address)
            mapped = getattr(ip, 'ipv4_mapped', None)
            if not ip.is_global or ip.is_multicast or ip.is_reserved or (mapped and not mapped.is_global):
                raise RetrievalError('Localhost, private, reserved and other non-public network addresses are blocked.')
        return parts, host, sorted(addresses)[0]
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, RetrievalError):
            raise
        raise RetrievalError(f'Cannot resolve a safe public URL: {exc}') from exc


@dataclass
class Page:
    url: str
    content: bytes
    mime: str
    text: str = ''
    identity_title: str = ''
    identity_key: str | None = None
    metadata_facts: dict = field(default_factory=dict)


class PublicRetriever:
    def __init__(self):
        self.robots = {}
        self.last_request = {}

    def _once(self, url):
        parts, host, address = public_target(url)
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        # Connect to the validated numeric IP, keeping certificate hostname/SNI.
        # A second DNS lookup cannot redirect the socket into a private network.
        if parts.scheme == 'https':
            pool = urllib3.HTTPSConnectionPool(address, port, assert_hostname=host, server_hostname=host,
                cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())
        else:
            pool = urllib3.HTTPConnectionPool(address, port)
        response = None
        try:
            path = urlunsplit(('', '', parts.path or '/', parts.query, ''))
            response = pool.urlopen('GET', path, headers={'Host': parts.netloc, 'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity'},
                redirect=False, retries=False, preload_content=False, timeout=urllib3.Timeout(connect=8, read=20))
            body, total, started = [], 0, time.monotonic()
            for chunk in response.stream(65536, decode_content=True):
                total += len(chunk)
                if total > MAX_BYTES or time.monotonic() - started > 45:
                    raise RetrievalError('Page exceeds the 10 MB or time limit; use a local upload instead.')
                body.append(chunk)
            return response.status, dict(response.headers), b''.join(body)
        except urllib3.exceptions.HTTPError as exc:
            raise RetrievalError('Page retrieval failed (network, TLS or timeout). Paste the ad or upload its PDF/DOCX instead.') from exc
        finally:
            if response:
                response.close()
            pool.close()

    def _allowed(self, url):
        parts = urlsplit(url)
        origin = f'{parts.scheme}://{parts.netloc}'
        if origin not in self.robots:
            current = origin + '/robots.txt'
            for _ in range(4):
                status, headers, content = self._once(current)
                headers = {k.lower(): v for k, v in headers.items()}
                if status in {301, 302, 303, 307, 308} and headers.get('location'):
                    current = urljoin(current, headers['location'])
                    continue
                break
            else:
                raise RetrievalError('Cannot verify robots.txt after redirects. Use manual import.')
            if status == 404:
                self.robots[origin] = None
            elif status == 200:
                parser = RobotFileParser()
                parser.parse(content.decode('utf-8', errors='replace').splitlines())
                self.robots[origin] = parser
            else:
                raise RetrievalError(f'Cannot verify site access restrictions (robots.txt HTTP {status}). Use manual import.')
        policy = self.robots[origin]
        if policy and not policy.can_fetch(USER_AGENT, url):
            raise RetrievalError('This site disallows automated retrieval in robots.txt. Paste the advertisement or upload a file.')
        delay = (policy.crawl_delay(USER_AGENT) or 0) if policy else 0
        rate = policy.request_rate(USER_AGENT) if policy else None
        if rate:
            delay = max(delay, rate.seconds / rate.requests)
        if delay > 30:
            raise RetrievalError('Site requests a long crawl delay. Use manual import instead.')
        remaining = max(1, delay) - (time.monotonic() - self.last_request.get(origin, 0))
        if remaining > 0:
            time.sleep(remaining)
        self.last_request[origin] = time.monotonic()

    def fetch(self, url):
        current = url
        for _ in range(6):
            public_target(current)
            self._allowed(current)
            status, headers, content = self._once(current)
            headers = {k.lower(): v for k, v in headers.items()}
            if status in {301, 302, 303, 307, 308} and headers.get('location'):
                current = urljoin(current, headers['location'])
                continue
            if status != 200:
                raise RetrievalError(f'Website returned HTTP {status}. No access restrictions were bypassed. Paste the ad or upload a file.')
            return Page(current, content, headers.get('content-type', '').split(';')[0].lower())
        raise RetrievalError('Too many redirects. Use manual import.')


def parse_page(page,expected_url=None):
    assert_target(expected_url or page.url,page.url)
    if page.mime == 'application/pdf' or page.content.startswith(b'%PDF'):
        page.text = read_upload('advertisement.pdf', page.content)
        return []
    if page.mime not in {'text/html', 'application/xhtml+xml', 'text/plain', ''}:
        raise RetrievalError('Unsupported web document type. Upload a PDF, DOCX or TXT file instead.')
    if page.mime == 'text/plain':
        page.text=page.content.decode('utf-8-sig')
        return []
    return clean_html(page,expected_url)


def import_url(db, url, retriever=None):
    from office.activity import activity
    with activity(db,1,'Retrieving job advertisement'):
        return _import_url(db,url,retriever)


def _import_url(db, url, retriever=None):
    from office.control import checkpoint
    retriever = retriever or PublicRetriever()
    page = retriever.fetch(url)
    checkpoint()
    links = parse_page(page,expected_url=url)
    job_id = db.add_job(page.text, url)
    db.add_source(job_id, page.url, page.content, page.text, page.mime, 'Primary advertisement')
    warnings = []
    pdfs = list(dict.fromkeys(href for label, href in links if urlsplit(href).path.lower().endswith('.pdf')
        or ('pdf' in label.lower() and any(w in label.lower() for w in ('description', 'specification', 'application', 'requirement')))))
    if len(pdfs) > 6:
        warnings.append(f'{len(pdfs)-6} additional PDF links were not downloaded (six-file limit). Review all source links manually.')
    combined = page.text
    for href in pdfs[:6]:
        checkpoint()
        try:
            pdf = retriever.fetch(href)
            if not pdf.content.startswith(b'%PDF'):
                raise RetrievalError('Linked document is not an accessible PDF.')
            parse_page(pdf)
            db.add_source(job_id, pdf.url, pdf.content, pdf.text, 'application/pdf', 'Linked supporting PDF; verify relevance')
            combined += f'\n\nSupporting document URL: {pdf.url}\n{pdf.text}'
        except (ValueError, OSError) as exc:
            note = f'Could not import linked PDF {href}: {exc}'
            warnings.append(note)
            db.add_source(job_id, href, b'', '', 'application/pdf', note)
    with db.connect() as conn:
        conn.execute('UPDATE jobs SET original=? WHERE id=?', (combined, job_id))
    if warnings:
        db.add_source(job_id, url, b'', '', 'text/plain', '\n'.join(warnings))
    return job_id, warnings
