from office.coordinator import build_tasks
from office.models import ground_analysis
from office.ollama import OllamaClient, PROMPT_VERSION
from office.chunks import split_text
from office.models import FACT_FIELDS, normalize, Fact, evidence_span
from office.analysis_input import inputs,save_input
from office.job_lock import exclusive_job
import json
from office.activity import tracked


def extract_sections(text,settings,depth=0,budget=None):
    budget = budget if budget is not None else [12]
    if budget[0]<=0:
        raise ValueError("Extraction call budget exhausted; manual review required.")
    budget[0]-=1
    from office.ollama import OllamaError
    try:
        part,raw=OllamaClient(settings).extract(text)
        yield text,part,raw
    except OllamaError as exc:
        if not getattr(exc,'raw_response',None) or depth>=2 or len(text.encode('utf-8'))<1400:
            raise
        limit=max(800,len(text.encode('utf-8'))//2)
        for section in split_text(text,limit=limit,overlap=150):
            yield from extract_sections(section,settings,depth+1,budget)


@tracked(2,'Analyzing job requirements')
@exclusive_job
def analyze_job(db, job_id, settings):
    job = db.job(job_id)
    with db.connect() as c:
        if c.execute('SELECT 1 FROM analysis_reviews WHERE job_id=?',(job_id,)).fetchone():
            raise ValueError('Reviewed analysis is protected. Create a corrected copy for review.')
    run_id = db.start_run(job_id, settings, PROMPT_VERSION)
    try:
        source_inputs,expected_title = inputs(db,job)
        authoritative={}
        for item in source_inputs:
            item['input_id']=save_input(db,job_id,run_id,item)
            for field,(value,quote) in item['facts'].items():
                authoritative[field]=Fact(value=value,source_quote=quote)
        chunks=list(dict.fromkeys(chunk for item in source_inputs for chunk in split_text(item['text'])))
        budget=[12]
        analysis, warnings, responses, seen = None, [], [], set()
        conflicts = set()
        def cached_sections():
            import hashlib
            from office.advertisement import PARSER_VERSION
            from office.models import Analysis
            for chunk in chunks:
                key=hashlib.sha256((str(job_id)+settings.model+settings.api_url+PROMPT_VERSION+PARSER_VERSION+chunk).encode()).hexdigest()
                with db.connect() as c:
                    cached=c.execute('SELECT * FROM extraction_cache WHERE key=?',(key,)).fetchone()
                if cached:
                    yield chunk,Analysis.model_validate_json(cached['analysis']),cached['raw']
                    continue
                parts=list(extract_sections(chunk,settings,budget=budget))
                if len(parts)==1 and parts[0][0]==chunk:
                    with db.connect() as c:
                        c.execute('INSERT OR REPLACE INTO extraction_cache(key,job_id,analysis,raw) VALUES(?,?,?,?)',(key,job_id,parts[0][1].model_dump_json(),parts[0][2]))
                yield from parts
        sections=cached_sections()
        processed=0
        for chunk,part,raw in sections:
            processed+=1
            part, notices = ground_analysis(part, chunk)
            responses.append({'chunk':chunk,'response':raw})
            for notice in notices:
                for field in authoritative:
                    if notice.startswith('Unsupported '+field+' removed'):
                        notice=f'Model {field} quote rejected; verified publisher metadata retained.'
                        break
                warnings.append(notice)
            if analysis is None:
                analysis = part.model_copy(deep=True)
                analysis.requirements = []
                for field,fact in authoritative.items():
                    setattr(analysis,field,fact)
            else:
                for field in FACT_FIELDS:
                    if field in authoritative:
                        continue
                    old, new = getattr(analysis, field), getattr(part, field)
                    if field in conflicts:
                        continue
                    if old.value is None:
                        setattr(analysis, field, new)
                    elif new.value and normalize(old.value) != normalize(new.value):
                        # Keep equivalent shorter/longer quotes, but expose genuine disagreement.
                        if normalize(old.value) in normalize(new.value) or normalize(new.value) in normalize(old.value):
                            continue
                        warnings.append(f'Conflicting {field}: {old.value!r} / {new.value!r}. Verify all sources; field marked unknown.')
                        old.value, old.source_quote = None, None
                        conflicts.add(field)
            for requirement in part.requirements:
                key = (requirement.category, normalize(requirement.text), requirement.importance)
                if key not in seen:
                    seen.add(key)
                    analysis.requirements.append(requirement)
        unique={}
        for requirement in analysis.requirements:
            key=normalize(requirement.text)
            if key not in unique:
                unique[key]=requirement
            elif unique[key].importance!=requirement.importance:
                unique[key].importance='unclear'
                warnings.append('Repeated criterion has inconsistent mandatory/preferred classification; verify importance.')
        analysis.requirements=list(unique.values())
        warnings=list(dict.fromkeys(warnings))
        if expected_title and normalize(analysis.title.value or '')!=normalize(expected_title):
            raise ValueError('Critical vacancy title mismatch; extraction requires manual review.')
        # Metadata quotes also pass the same exact-evidence validation.
        analysis,final_notices=ground_analysis(analysis,'\n'.join(item['text'] for item in source_inputs))
        warnings=list(dict.fromkeys(warnings+final_notices))
        tasks = build_tasks(analysis, warnings)
        for source in db.sources(job_id):
            if 'Could not' in source['note'] or 'not downloaded' in source['note']:
                tasks.append({'text': 'Retrieve and review supporting material manually: ' + source['note'], 'source': source['url'], 'verification': True, 'importance': 'review'})
        db.save_analysis(job_id, analysis, warnings, tasks, run_id, json.dumps(responses),expected=job)
        with db.connect() as c:
            claims=[(field,getattr(analysis,field).source_quote) for field in FACT_FIELDS]
            claims += [('requirement:'+r.category,r.source_quote) for r in analysis.requirements]
            for field,quote in claims:
                if not quote:
                    continue
                for item in source_inputs:
                    span=evidence_span(item['text'],quote)
                    if span:
                        c.execute('INSERT INTO analysis_evidence(job_id,run_id,input_id,field,quote,start_offset,end_offset) VALUES(?,?,?,?,?,?,?)',
                                  (job_id,run_id,item['input_id'],field,item['text'][span[0]:span[1]],*span))
                        break
        return analysis
    except Exception as exc:
        db.fail_run(run_id, str(exc), getattr(exc, 'raw_response', ''))
        raise
