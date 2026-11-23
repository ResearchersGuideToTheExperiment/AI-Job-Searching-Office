"""Public listing adapters. No assumed APIs, credentials or browser bypasses."""
import re
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from bs4 import BeautifulSoup
from office.retrieval import PublicRetriever

def canonical(url):
    p = urlsplit(url)
    query = [(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in {'fbclid','gclid'}]
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/'),urlencode(sorted(query)),''))


def studentship(title):
    return bool(re.search(r'\b(ph\.?d\.?\s*(studentship|student|candidate|position|scholarship)|doctoral\s*(student|candidate|studentship)|studentship)\b',title,re.I))


def automatic_vacancy_link(url, listing_url):
    """Conservative URL recognition; detail identity is validated on retrieval."""
    p=urlsplit(url);base=urlsplit(listing_url)
    if p.scheme not in {'http','https'} or p.hostname!=base.hostname or p.path.rstrip('/')==base.path.rstrip('/'):
        return False
    path=p.path.lower().rstrip('/')
    if re.search(r'/(?:privacy|cookies|login|register|search|categories|departments|job-alerts)(?:/|$)',path):
        return False
    # Explicit vacancy-detail paths with an identifier, including VU slugs.
    return bool(re.search(r'/(?:jobs?|vacancies|vacancy|positions?)/(?:[^/]+/)*[^/]*[0-9][^/]*$',path)
                or ('seekjordetail' in path and p.query))


def discover(source, retriever=None):
    if not source.get('url'):
        return {'state':'requires_configuration','detail':'A listing URL is required.','jobs':[]}
    try:
        page = (retriever or PublicRetriever()).fetch(source['url'])
        soup = BeautifulSoup(page.content, 'html.parser')
        jobs = {}
        for anchor in soup.find_all('a', href=True):
            url = canonical(urljoin(page.url, anchor['href']))
            if urlsplit(url).scheme in {'http','https'} and (re.search(source['pattern'], url) if source.get('pattern') else automatic_vacancy_link(url,page.url)):
                title = anchor.get_text(' ',strip=True) or anchor.get('aria-label') or urlsplit(url).path.rsplit('/',1)[-1].replace('-',' ')
                if url not in jobs or len(title) > len(jobs[url]['title']):
                    jobs[url] = {'url':url,'title':title,'source':source['name']}
        suggestions={}
        for anchor in soup.find_all('a',href=True):
            label=anchor.get_text(' ',strip=True)
            url=canonical(urljoin(page.url,anchor['href']))
            if (urlsplit(url).scheme in {'http','https'} and url not in jobs
                and re.search(r'careers?|vacancies|job opportunities|recruitment|jobs board',label,re.I)):
                suggestions[url]={'url':url,'name':label[:120]}
        return {'state':'working' if jobs else 'unavailable','detail':f'{len(jobs)} vacancy links found.' if jobs else 'No individual vacancy links could be recognized in accessible HTML. This website may need a dedicated adapter.','jobs':list(jobs.values()),'suggestions':list(suggestions.values())[:20]}
    except Exception as exc:
        message = str(exc)
        return {'state':'blocked' if any(x in message.lower() for x in ['disallow','403','captcha','access restriction']) else 'unavailable','detail':message,'jobs':[]}
