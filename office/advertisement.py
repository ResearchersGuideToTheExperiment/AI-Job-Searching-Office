"""Select one vacancy, not an entire website, before any model sees text."""
import re
import json
from urllib.parse import urlsplit,urljoin
from bs4 import BeautifulSoup

PARSER_VERSION='vacancy-main-v2'


class IdentityError(ValueError):
    pass


def vacancy_key(url):
    p=urlsplit(url or '')
    host=(p.hostname or '').lower().removeprefix('www.')
    match=re.search(r'/jobs?/([A-Za-z0-9]+)(?:/|$)',p.path)
    return host+':'+match[1].upper() if match else None


def assert_target(requested,actual):
    expected=vacancy_key(requested)
    if expected and vacancy_key(actual)!=expected:
        raise IdentityError(f'Vacancy identity mismatch: requested {expected}, received {actual}. Manual import required.')


def clean_html(page,expected_url=None):
    expected_url=expected_url or page.url
    assert_target(expected_url,page.url)
    soup=BeautifulSoup(page.content,'html.parser')
    canonical=soup.select_one('link[rel="canonical"]')
    if canonical and canonical.get('href'):
        assert_target(expected_url,urljoin(page.url,canonical['href']))
    title=soup.title.get_text(' ',strip=True).lower() if soup.title else ''
    if any(x in title for x in ('just a moment','access denied','captcha','verify you are human','sign in','log in')):
        raise IdentityError('Blocked/login page is not a vacancy. Manual import required.')
    if (urlsplit(page.url).hostname or '').removeprefix('www.')=='jobs.ac.uk':
        heading=soup.select_one('h1.j-advert__title')
        description=soup.select_one('#job-description')
        if not vacancy_key(page.url) or not heading or not description:
            raise IdentityError('jobs.ac.uk page has no isolated target advertisement; category/search fallback is forbidden.')
        slug=urlsplit(page.url).path.rstrip('/').split('/')[-1]
        if len(slug)>12 and '-' in slug:
            words=set(re.findall(r'[a-z]{3,}',slug.lower()))-{'phd','studentship','the','and','for','with','job'}
            title_words=set(re.findall(r'[a-z]{3,}',heading.get_text(' ',strip=True).lower()))
            if words and len(words & title_words)/len(words)<.6:
                raise IdentityError('Vacancy heading does not match its URL title; manual verification required.')
        nodes=[heading,soup.select_one('.j-advert__employer'),soup.select_one('.j-advert-details__container'),description]
        button=soup.select_one('#job-apply-button')
        if button:
            anchor=button.find_parent('a',href=True)
            if anchor:
                # Input value is a visible label, even when the anchor has no text.
                anchor.clear();anchor.append('Apply')
                nodes.append(anchor)
        root=BeautifulSoup('<article></article>','html.parser').article
        for node in nodes:
            if node:
                root.append(node.extract())
    else:
        postings=[]
        def collect(value):
            if isinstance(value,dict):
                if value.get('@type')=='JobPosting': postings.append(value)
                for child in value.values(): collect(child)
            elif isinstance(value,list):
                for child in value: collect(child)
        for script in soup.select('script[type="application/ld+json"]'):
            try: collect(json.loads(script.get_text()))
            except (ValueError,TypeError): pass
        if len(postings)>1:
            raise IdentityError('Multiple structured vacancies; manual isolation required.')
        if postings:
            posting=postings[0]
            visible=soup.find('h1')
            if not visible or visible.get_text(' ',strip=True).casefold()!=str(posting.get('title','')).casefold():
                raise IdentityError('Structured vacancy title differs from visible heading.')
            root=BeautifulSoup('<article><h1></h1></article>','html.parser')
            root.h1.string=posting['title']
            for field in ('description','qualifications','responsibilities','skills','educationRequirements','experienceRequirements','employmentType','jobBenefits','applicationContact','url','validThrough','hiringOrganization','jobLocation','baseSalary'):
                value=posting.get(field)
                if value:
                    if isinstance(value,(dict,list)): value=json.dumps(value,ensure_ascii=False)
                    node=root.new_tag('section');node.append(field+': ')
                    node.append(BeautifulSoup(str(value),'html.parser'));root.article.append(node)
            soup=root
        for node in soup.select('nav,header,footer,aside,script,style,noscript,template,[role="navigation"],[role="dialog"],.related-jobs,.recommended-jobs,.job-alerts,.advertisement'):
            node.decompose()
        root=soup.select_one('[itemtype="https://schema.org/JobPosting"],main,article') or soup.body or soup
        headings=root.find_all('h1')
        if len(headings)!=1:
            raise IdentityError('Cannot identify one vacancy heading; use a manually isolated advertisement.')
        heading=headings[0]
        foreign={vacancy_key(urljoin(page.url,a['href'])) for a in root.find_all('a',href=True)}-{None,vacancy_key(page.url)}
        if len(foreign)>1:
            raise IdentityError('Multiple vacancy identities remain in main content; manual isolation required.')
    page.identity_title=heading.get_text(' ',strip=True)
    page.identity_key=vacancy_key(expected_url)
    links=[]
    for a in root.find_all('a',href=True):
        href=urljoin(page.url,a['href'])
        if urlsplit(href).scheme in {'https','http','mailto'}:
            if vacancy_key(href) and vacancy_key(href)!=vacancy_key(expected_url):
                a.decompose()
                continue
            label=a.get_text(' ',strip=True)
            links.append((label,href))
            a.append(' ['+href+']')
    for node in root.select('script,style,noscript,template'):
        node.decompose()
    # Render each metadata row together, without adding Markdown table syntax.
    for row in root.select('tr'):
        row.replace_with(soup.new_string(' '.join(row.get_text(' ',strip=True).split())+'\n'))
    page.text=root.get_text('\n',strip=True)
    page.metadata_facts={'title':(page.identity_title,page.identity_title)}
    employer=root.select_one('.j-advert__employer')
    if employer:
        employer_text=employer.get_text(' ',strip=True)
        # Keep the exact employer/department text shown by the publisher.
        page.metadata_facts['institution']=(employer_text,employer.get_text('\n',strip=True))
    labels={'location':'Location','job_type':'Qualification Type','deadline':'Closes','salary':'Salary'}
    for field,label in labels.items():
        match=re.search(r'^'+label+r':\s*([^\n]+)',page.text,re.M)
        if match:
            page.metadata_facts[field]=(match[1].strip(),match[0])
    if 'job_type' not in page.metadata_facts:
        match=re.search(r'^Contract Type:\s*([^\n]+)',page.text,re.M)
        if match:
            page.metadata_facts['job_type']=(match[1].strip(),match[0])
    for label,href in links:
        if label.lower()=='apply':
            page.metadata_facts['application_url']=(href,'Apply ['+href+']')
    if len(page.text.strip())<120:
        raise IdentityError('Too little isolated vacancy content; manual import required.')
    return list(dict.fromkeys(links))
