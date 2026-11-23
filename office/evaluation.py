import hashlib
import json
from typing import Literal
from pydantic import Field
from office.models import StrictModel, Analysis, normalize
from office.career import profile_fingerprint
from office.ollama import OllamaClient, OllamaError
from office.activity import tracked
from office.job_lock import exclusive_job


def analysis_fingerprint(analysis):
    return hashlib.sha256(analysis.model_dump_json().encode()).hexdigest()


class Evidence(StrictModel):
    fact_id: int
    quote: str


class CriterionMatch(StrictModel):
    result: Literal['satisfied', 'partial', 'not_satisfied', 'unknown']
    explanation: str
    evidence: list[Evidence]
    eligibility_concern: str | None


class CompactDecision(StrictModel):
    result: Literal['satisfied','partial','not_satisfied','unknown']
    explanation: str = Field(max_length=240)
    fact_ids: list[int] = Field(max_length=3)
    eligibility_concern: str | None = Field(max_length=160)


EVALUATION_VERSION='compact-ids-v1'


def compare_batch(db,job_id,client,criterion,batch,context_key,depth=0):
    data={'criterion':criterion.model_dump(),'confirmed_facts':batch}
    key=hashlib.sha256((context_key+json.dumps(data,ensure_ascii=False,sort_keys=True)).encode()).hexdigest()
    with db.connect() as c:
        cached=c.execute('SELECT payload FROM evaluation_steps WHERE key=?',(key,)).fetchone()
    if cached:
        return [CriterionMatch.model_validate(row) for row in json.loads(cached['payload'])]
    try:
        reply=client.structured(CompactDecision,
            'Compare ONE criterion with these confirmed facts. Return one short JSON decision. '
            'Use at most 3 fact_ids from this batch; never repeat fact text. Keep explanation to one short sentence (max 240 characters). '
            'Satisfied requires direct evidence for the full criterion; partial means transferable or incomplete evidence. '
            'Not_satisfied requires explicit contradictory evidence. Missing evidence is unknown, not a disqualification. '
            'Other profile sections may follow. Never infer citizenship, eligibility, qualifications or legal status. '
            'Use null for eligibility_concern unless there is a concrete uncertainty; max 160 characters.',data,max_output_tokens=512)
        lookup={fact['id']:fact['text'] for fact in batch}
        if any(ident not in lookup for ident in reply.fact_ids) or (reply.result!='unknown' and not reply.fact_ids):
            matches=[CriterionMatch(result='unknown',explanation='AI judgment lacked valid profile evidence; verify manually.',evidence=[],eligibility_concern='Needs verification' if criterion.category=='eligibility' else None)]
        else:
            matches=[CriterionMatch(result=reply.result,explanation=reply.explanation,
                evidence=[Evidence(fact_id=ident,quote=lookup[ident]) for ident in dict.fromkeys(reply.fact_ids)],eligibility_concern=reply.eligibility_concern)]
    except OllamaError as exc:
        if getattr(exc,'kind',None) not in {'output_limit','schema'}:
            raise
        if depth>=1 or len(batch)<2:
            raise OllamaError('Compact evaluation still failed. Completed comparisons are saved; manual review or retry is needed. '+str(exc)) from exc
        middle=len(batch)//2
        matches=compare_batch(db,job_id,client,criterion,batch[:middle],context_key,depth+1)+compare_batch(db,job_id,client,criterion,batch[middle:],context_key,depth+1)
    with db.connect() as c:
        c.execute('INSERT OR REPLACE INTO evaluation_steps(key,job_id,payload) VALUES(?,?,?)',
                  (key,job_id,json.dumps([m.model_dump() for m in matches])))
    return matches


def fact_batches(facts, limit=3000):
    batches, batch, size = [], [], 0
    for fact in facts:
        item = {k: fact[k] for k in ('id', 'category', 'text')}
        cost = len(json.dumps(item, ensure_ascii=False).encode())
        if cost > 6500:
            raise ValueError('A profile fact is too long. Split it into smaller reviewed facts.')
        if size + cost > limit and batch:
            batches.append(batch)
            batch, size = [], 0
        batch.append(item)
        size += cost
    if batch:
        batches.append(batch)
    return batches


def validate_evidence(evidence, facts):
    lookup = {f['id']: f['text'] for f in facts}
    return all(e.fact_id in lookup and e.quote.strip() and normalize(e.quote) in normalize(lookup[e.fact_id]) for e in evidence)


@tracked(2,'Evaluating job suitability')
@exclusive_job
def evaluate_job(db, job_id, settings, progress=None, *, automatic=False):
    from office.analysis_input import needs_refresh
    if needs_refresh(db,job_id):
        raise ValueError('Legacy webpage extraction needs clean reanalysis before evaluation. Reviewed data must be copied, not overwritten.')
    job = db.job(job_id)
    with db.connect() as c:
        version=c.execute('SELECT revision FROM case_state WHERE job_id=?',(job_id,)).fetchone()
        revision=version['revision'] if version else 0
    if not job['analysis']:
        raise ValueError('Analyze and review the job first.')
    analysis = Analysis.model_validate_json(job['analysis'])
    digest = analysis_fingerprint(analysis)
    if not automatic and not db.is_analysis_reviewed(job_id, digest):
        raise ValueError('Review the extracted job requirements in Job Details and confirm that review first.')
    facts = db.facts(True)
    if not facts:
        raise ValueError('Confirm your career facts in My Profile before evaluating a job.')
    criteria = [(i, r) for i, r in enumerate(analysis.requirements) if r.category in {'eligibility','essential','desirable'}]
    run = db.operation_start('suitability evaluation', settings.model, job_id)
    try:
        client, rows = OllamaClient(settings), []
        context_key=json.dumps([job_id,EVALUATION_VERSION,settings.model,settings.api_url,digest,profile_fingerprint(facts)])
        for number, (index, criterion) in enumerate(criteria):
            matches = []
            for batch_index, batch in enumerate(fact_batches(facts)):
                if progress:
                    progress(f'Evaluating criterion {number + 1}/{len(criteria)}, profile section {batch_index + 1}')
                matches.extend(compare_batch(db,job_id,client,criterion,batch,context_key))
            meaningful = [m for m in matches if m.result != 'unknown']
            results = {m.result for m in meaningful}
            if 'not_satisfied' in results and len(results) > 1:
                result = 'unknown'
                summary = 'Conflicting evidence across profile sections. Resolve before relying on the score.'
            elif 'satisfied' in results:
                result, summary = 'satisfied', next(m.explanation for m in meaningful if m.result == 'satisfied')
            elif 'partial' in results:
                result, summary = 'partial', next(m.explanation for m in meaningful if m.result == 'partial')
            elif 'not_satisfied' in results:
                result, summary = 'not_satisfied', meaningful[0].explanation
            else:
                result, summary = 'unknown', 'Not determinable from the confirmed profile. Add or clarify evidence.'
            weight = 1 if criterion.category == 'desirable' or criterion.importance == 'preferred' else 2
            rows.append({'criterion_index': index, 'criterion': criterion.text, 'category': criterion.category,
                'importance': criterion.importance, 'source_quote': criterion.source_quote, 'weight': weight,
                'result': result, 'explanation': summary, 'evidence': [e.model_dump() for m in matches for e in m.evidence],
                'section_judgments': [m.model_dump() for m in matches],
                'eligibility_concern': criterion.category == 'eligibility' and result != 'satisfied'})
        denominator = sum(r['weight'] for r in rows)
        score = round(100 * sum(r['weight'] * {'satisfied': 1, 'partial': .5, 'not_satisfied': 0, 'unknown': 0}[r['result']] for r in rows) / denominator) if denominator else None
        payload = {'score': score, 'criteria': rows, 'formula': '100 × weighted evidence points / total criterion weights. Essential and eligibility weight 2; desirable/preferred weight 1. Satisfied=1, partial=0.5, not satisfied=0, unknown=0.',
            'unknown_count': sum(r['result'] == 'unknown' for r in rows), 'profile_snapshot': facts,
            'preferences': db.preferences()['preferences'], 'note': 'Evidence coverage, not hiring probability. Unknowns lower the score and are not proof of ineligibility. Preferences are shown separately and do not establish qualifications.'}
        if profile_fingerprint(facts) != profile_fingerprint(db.facts(True)) or digest != analysis_fingerprint(Analysis.model_validate_json(db.job(job_id)['analysis'])):
            raise ValueError('Profile or job changed during evaluation. Please rerun with the current evidence.')
        evaluation_id = db.save_evaluation(job_id, profile_fingerprint(facts), digest, payload,expected_revision=revision)
        db.operation_finish(run, 'success', f'Evaluation {evaluation_id}; {len(rows)} criteria')
        return payload
    except Exception as exc:
        db.operation_finish(run, 'failed', str(exc))
        raise


def evaluation_current(db, job_id, evaluation):
    from office.analysis_input import needs_refresh
    job = db.job(job_id)
    with db.connect() as c:
        case=c.execute('SELECT evaluation_dirty FROM case_state WHERE job_id=?',(job_id,)).fetchone()
    if case and case['evaluation_dirty']:
        return False
    return bool(evaluation and job['analysis'] and evaluation['profile_hash'] == profile_fingerprint(db.facts(True))
        and evaluation['analysis_hash'] == analysis_fingerprint(Analysis.model_validate_json(job['analysis']))) and not needs_refresh(db,job_id)
