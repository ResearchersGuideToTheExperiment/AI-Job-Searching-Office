import json
import threading
from pathlib import Path
import pytest
from office.retrieval import Page,parse_page,import_url,PublicRetriever,RetrievalError
from office.advertisement import IdentityError
from office.models import Analysis,Fact,Requirement,FACT_FIELDS,ground_analysis
from office.db import Database
from office.config import Settings
from office.service import analyze_job,extract_sections
from office.ollama import OllamaClient,OllamaError
from office.evaluation import evaluate_job,CompactDecision,analysis_fingerprint

CRAB='https://www.jobs.ac.uk/job/SYN001/phd-studentship-sample-materials'
MINE='https://www.jobs.ac.uk/job/SYN002/unrelated-vacancy'
HTML=(Path(__file__).parent/'fixtures/studentship.html').read_bytes()


def empty():
    return Analysis(**{k:Fact(value=None,source_quote=None) for k in FACT_FIELDS},requirements=[])


def test_synthetic_studentship_main_content_and_provenance():
    page=Page(CRAB,HTML,'text/html')
    links=parse_page(page,CRAB)
    assert len(page.text)<3500
    for unwanted in ('Unrelated','SYN002','Create Account','Privacy Policy','Job Alert','Find a Job','send us your feedback'):
        assert unwanted not in page.text
    assert page.identity_key=='jobs.ac.uk:SYN001'
    assert 'Sample Materials' in page.identity_title
    assert page.metadata_facts['deadline'][0]=='7th January 2099'
    assert ('Apply','https://funding.example.org/award/100') in links
    assert page.content==HTML


@pytest.mark.parametrize('actual,body',[(MINE,HTML),(CRAB,HTML.replace(b'/job/SYN001/',b'/job/SYN002/')),
                                      (CRAB,b'<h1>Search results</h1><a href="/job/SYN002/">Unrelated Vacancy</a>')])
def test_wrong_identity_and_category_substitution_fail_closed(actual,body):
    with pytest.raises(IdentityError):
        parse_page(Page(actual,body,'text/html'),CRAB)


def test_403_never_falls_back_or_saves_category_content(tmp_path,monkeypatch):
    import office.retrieval as r
    monkeypatch.setattr(r,'public_target',lambda u:None)
    client=PublicRetriever();seen=[]
    monkeypatch.setattr(client,'_allowed',lambda u:None)
    def blocked(url):
        seen.append(url)
        return 403,{},b'<h1>Category page</h1>'
    monkeypatch.setattr(client,'_once',blocked)
    db=Database(tmp_path/'office.db')
    with pytest.raises(RetrievalError,match='403'):
        import_url(db,CRAB,client)
    assert seen==[CRAB] and not db.jobs()


def test_formatting_normalization_preserves_verbatim_and_rejects_fabrication():
    text='Applicants must have a Master’s degree in human–computer interaction. Salary: £40,000.'
    result=empty()
    quote="Applicants must have a Master's degree in human-computer interaction."
    result.requirements=[Requirement(category='essential',text=quote,source_quote=quote,importance='mandatory')]
    result.salary=Fact(value='£80,000',source_quote='Salary: £40,000.')
    checked,notices=ground_analysis(result,text)
    assert checked.requirements[0].source_quote==text.split(' Salary')[0]
    assert checked.requirements[0].text==checked.requirements[0].source_quote
    assert checked.salary.value is None
    result=empty();result.location=Fact(value='eligible',source_quote='ineligible')
    assert ground_analysis(result,'ineligible')[0].location.value is None


def test_research_to_evaluation_isolated_vacancy_and_optional_unknowns(tmp_path,monkeypatch):
    from office import autonomous as a
    from office.discovery import discover
    db=Database(tmp_path/'office.sqlite3');db.save_fact(None,'research','Research experience.',True)
    monkeypatch.setattr(a,'DATA',tmp_path)
    monkeypatch.setattr(a,'config',lambda:a.OfficeSettings(include_studentships=True,sources=[{'name':'fixture'}]))
    monkeypatch.setattr(a,'sync_local_files',lambda db:None)
    class Retriever:
        def fetch(self,url):
            if url.endswith('/listing'):
                return Page(url,f'<a href="{CRAB}">Sample Materials PhD studentship</a>'.encode(),'text/html')
            return Page(CRAB,HTML,'text/html')
    monkeypatch.setattr(a,'discover',lambda source:discover({'name':'fixture','url':'https://www.jobs.ac.uk/listing','pattern':'/job/'},Retriever()))
    monkeypatch.setattr(a,'import_url',lambda db,url:import_url(db,url,Retriever()))
    calls=[]
    def extract(self,text):
        calls.append(text);assert 'SYN002' not in text and 'Unrelated' not in text
        result=empty()
        result.title=Fact(value='Unrelated Vacancy',source_quote='Unrelated Vacancy')
        quote='Eligible applicants receive tuition support and an annual stipend for this example programme.'
        result.requirements=[Requirement(category='eligibility',text=quote,source_quote=quote,importance='unclear')]*3
        return result,result.model_dump_json()
    monkeypatch.setattr(OllamaClient,'extract',extract)
    monkeypatch.setattr(OllamaClient,'test_connection',lambda self:'ok')
    def structured(self,schema,*args,**kwargs):
        if schema is a.Relevance:
            return a.Relevance(relevant=False,region_match=True,reason='Studentship, below career level.')
        return CompactDecision(result='unknown',explanation='Not established',fact_ids=[],eligibility_concern='Verify funding eligibility')
    monkeypatch.setattr(OllamaClient,'structured',structured)
    report=a.run()
    assert report['assessed']==1 and report['errors']==0 and report['prepared']==0
    analysis=Analysis.model_validate_json(db.job(1)['analysis'])
    assert 'Sample Materials' in analysis.title.value
    assert analysis.institution.value.startswith('Example University')
    assert analysis.salary.value is None and analysis.application_email.value is None
    assert len(analysis.requirements)==1 and len(calls)==1
    assert db.evaluation(1)
    warnings=json.loads(db.job(1)['warnings']);assert len(warnings)==len(set(warnings))
    with db.connect() as c:
        evidence=[dict(r) for r in c.execute('SELECT e.*,i.text,i.url FROM analysis_evidence e JOIN analysis_inputs i ON i.id=e.input_id')]
    assert evidence and all(r['quote']==r['text'][r['start_offset']:r['end_offset']] and r['url']==CRAB for r in evidence)
    db.review_analysis(1,analysis_fingerprint(analysis))
    original=db.job(1)
    with pytest.raises(ValueError,match='protected'):
        analyze_job(db,1,Settings())
    assert db.job(1)==original


def test_source_and_database_job_identity_cannot_cross(tmp_path):
    db=Database(tmp_path/'office.db');job=db.add_job('Original',CRAB)
    db.add_source(job,MINE,HTML,'mixed','text/html','Primary advertisement')
    with pytest.raises(IdentityError):
        analyze_job(db,job,Settings())
    assert db.job(job)['analysis'] is None


def test_same_job_concurrency_rejected(tmp_path):
    from office.job_lock import exclusive_job
    db=Database(tmp_path/'office.db');entered=threading.Event();release=threading.Event()
    @exclusive_job
    def work(db,job_id,wait=False):
        if wait:
            entered.set();release.wait(3)
        return job_id
    thread=threading.Thread(target=work,args=(db,36,True));thread.start()
    try:
        assert entered.wait(2)
        with pytest.raises(ValueError,match='already being processed'):
            work(db,36)
        assert work(db,37)==37
    finally:
        release.set();thread.join(3)


def test_extraction_retries_have_total_budget(monkeypatch):
    calls=[]
    def broken(self,text):
        calls.append(text);error=OllamaError('Output length');error.raw_response='{';raise error
    monkeypatch.setattr(OllamaClient,'extract',broken)
    with pytest.raises((OllamaError,ValueError)):
        list(extract_sections('word '*1500,Settings(),budget=[2]))
    assert len(calls)<=2


def test_studentship_filter_does_not_exclude_postdocs():
    from office.discovery import studentship
    assert studentship('PhD Studentship - Sample Materials')
    assert studentship('Doctoral candidate in cognitive science')
    assert not studentship('Postdoctoral Research Fellow (PhD required)')
