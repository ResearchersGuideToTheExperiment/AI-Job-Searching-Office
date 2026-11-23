"""Re-clean immutable source snapshots; retain per-run provenance."""
import hashlib
import re
from office.retrieval import Page,parse_page
from office.advertisement import IdentityError,assert_target,PARSER_VERSION
from office.models import normalize


def inputs(db,job, *, use_override=True):
    from office.content_cleaner import clean_text,document_relevant
    with db.connect() as c:
        override=c.execute('SELECT text_override FROM case_state WHERE job_id=?',(job['id'],)).fetchone()
    if use_override and override and override['text_override']:
        return [{'source_id':None,'url':job['source_url'],'text':clean_text(override['text_override']),'facts':{}}],''
    sources=db.sources(job['id'])
    primary=next((s for s in sources if s['note']=='Primary advertisement'),None)
    if not primary:
        return [{'source_id':None,'url':job['source_url'],'text':clean_text(job['original']),'facts':{}}],''
    page=Page(primary['url'],primary['content'],primary['mime'])
    links=parse_page(page,expected_url=job['source_url'])
    result=[{'source_id':primary['id'],'url':page.url,'text':clean_text(page.text),'facts':page.metadata_facts}]
    allowed={url for _,url in links}
    for source in sources:
        if source['id']==primary['id'] or not source['content']:
            continue
        # Legacy page-wide links are not evidence of a relationship to this vacancy.
        if source['url'] not in allowed:
            continue
        secondary=Page(source['url'],source['content'],source['mime'])
        parse_page(secondary)
        label=next((label for label,url in links if url==source['url']),'')
        if not document_relevant(label,source['url'],secondary.text,page.identity_title):
            continue
        if page.identity_key and page.identity_key.startswith('jobs.ac.uk:'):
            mentioned=set(re.findall(r'\bDT[A-Z]\d{3}\b',secondary.text))
            if mentioned and page.identity_key.split(':')[-1] not in mentioned:
                raise IdentityError('Supporting document identifies a different jobs.ac.uk vacancy; not merged.')
        if secondary.mime!='application/pdf' and normalize(page.identity_title) not in normalize(secondary.text):
            raise IdentityError('Application page does not identify the target vacancy. Review it manually.')
        result.append({'source_id':source['id'],'url':source['url'],'text':clean_text(secondary.text),'facts':{}})
    return result,page.identity_title


def save_input(db,job_id,run_id,item):
    with db.connect() as c:
        return c.execute('INSERT INTO analysis_inputs(job_id,run_id,source_id,url,parser_version,content_hash,text) VALUES(?,?,?,?,?,?,?)',
            (job_id,run_id,item['source_id'],item['url'],PARSER_VERSION,hashlib.sha256(item['text'].encode()).hexdigest(),item['text'])).lastrowid


def needs_refresh(db,job_id):
    if not any(s['note']=='Primary advertisement' for s in db.sources(job_id)):
        return False
    with db.connect() as c:
        latest=c.execute("SELECT id FROM history WHERE job_id=? AND outcome='success' ORDER BY id DESC LIMIT 1",(job_id,)).fetchone()
        return not latest or not c.execute('SELECT 1 FROM analysis_inputs WHERE run_id=? AND parser_version=?',(latest['id'],PARSER_VERSION)).fetchone()
