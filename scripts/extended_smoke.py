"""Live local-model workflow using SYNTHETIC profile/job data in an isolated folder."""
import argparse
from io import BytesIO
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docx import Document
from office.config import ROOT, load_settings
from office.db import Database
from office.retrieval import Page, import_url, PublicRetriever, RetrievalError
from office.career import upload_career, extract_career
from office.service import analyze_job
from office.evaluation import evaluate_job, analysis_fingerprint
from office.documents import prepare_package, generate_document


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT / 'data' / 'synthetic-validation'))
    parser.add_argument('--probe-url', help='Optional public vacancy URL; omitted for a synthetic-only run.')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    db = Database(output / 'validation.sqlite3')
    settings = load_settings()
    report = {}
    report['public_url_probe'] = {'status': 'not_requested'}
    if args.probe_url:
        try:
            probe_job, notices = import_url(db, args.probe_url)
            report['public_url_probe'] = {'status': 'retrieved', 'job_id': probe_job, 'notices': notices}
        except Exception as exc:
            report['public_url_probe'] = {'status': 'blocked_or_unavailable', 'reason': str(exc)}
    print('PUBLIC URL:', report['public_url_probe'], flush=True)
    html = (ROOT / 'samples' / 'research_job.html').read_bytes()
    class SyntheticRetriever:
        def fetch(self, url):
            return Page(url, html, 'text/html')
    job, _ = import_url(db, 'https://university.example/synthetic-research-job', SyntheticRetriever())
    doc = Document()
    doc.add_heading('Alex Example', 0)
    doc.add_paragraph('PhD in Psychology, Example University, 2022.')
    doc.add_paragraph('Designed virtual reality experiments on visual perception and tested 40 participants.')
    doc.add_paragraph('Taught research methodology to undergraduate students from 2022 to 2024.')
    content = BytesIO()
    doc.save(content)
    doc_id = upload_career(db, 'synthetic-master-cv.docx', content.getvalue(), 'master_cv')
    extract_career(db, doc_id, settings, lambda s: print(s, flush=True))
    facts = db.facts()
    assert facts and not db.facts(True)
    # Synthetic-only fixture review: extracted facts are exact source substrings.
    for fact in facts:
        assert fact['text'] in db.profile_document(doc_id)['text']
        db.save_fact(fact['id'], fact['category'], fact['text'], True)
    print('PROFILE: extracted and fixture-reviewed', len(facts), flush=True)
    analysis = analyze_job(db, job, settings)
    assert analysis.salary.value is None
    assert analysis.application_url.value == 'https://careers.example.org/apply/visual-perception'
    assert any(r.category == 'question' for r in analysis.requirements)
    db.review_analysis(job, analysis_fingerprint(analysis))
    print('JOB: extracted; missing salary remains unknown', flush=True)
    evaluation = evaluate_job(db, job, settings, lambda s: print(s, flush=True))
    assert len(evaluation['criteria']) >= 3
    report['evaluation'] = evaluation
    print('EVALUATION:', evaluation['score'], flush=True)
    from office.decisions import save_decision
    assert evaluation['score'] is not None
    save_decision(db, job, db.evaluation(job)['id'], evaluation['score'], 'approved',
                  'Synthetic smoke fixture only; never approves user applications.')
    prepare_package(db, job)
    plan = json.loads(db.package(job)['plan'])
    assert {'cv','cover_letter','answer'}.issubset({p['kind'] for p in plan})
    paths = []
    for item in plan:
        if not item['manual']:
            print('GENERATING:', item['title'], flush=True)
            paths.append(str(generate_document(db, job, item['key'], settings)))
    tasks = db.tasks(job)
    assert any('https://careers.example.org/apply/visual-perception' in t['text'] for t in tasks)
    db.set_complete(tasks[0]['id'], True)
    assert Database(db.path).tasks(job)[0]['complete'] == 1
    assert db.profile_document(doc_id)['content'] == content.getvalue()
    report.update({'job_id': job, 'documents': paths, 'plan': plan, 'result': 'PASS', 'note': 'Synthetic fixture retrieval plus real local-model extraction, evaluation, drafting and audit. Public URL probe reported separately.'})
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('PASS:', output / 'report.json', flush=True)


if __name__ == '__main__':
    main()
