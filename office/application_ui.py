"""One workspace for the advert, profile fit, letter, materials and application status."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st

from office.control import Cancelled
from office.decisions import require_approval
from office.documents import ALIASES, check_limits, count_words, generate_document, plan_documents, prepare_package, save_version
from office.evaluation import evaluation_current
from office.models import Analysis


def motivation_item(plan):
    letter = next((item for item in plan if item['kind'] == 'cover_letter' and not item['manual']), None)
    if letter:
        return letter
    # A cover letter may be requested inside the supporting statement.
    return next((item for item in plan if item['kind'] == 'supporting_statement'
                 and re.search(ALIASES['cover_letter'], item['source_quote'], re.I)), None)


def current_package(db, job_id):
    require_approval(db, job_id)
    evaluation = db.evaluation(job_id)
    if not evaluation_current(db, job_id, evaluation):
        raise ValueError('The job or profile changed. Evaluate and approve it again in Job Processing.')
    package = db.package(job_id)
    if not package or package['evaluation_id'] != evaluation['id']:
        prepare_package(db, job_id)
        package = db.package(job_id)
    return package


def save_letter(db, job_id, item_key, text, evaluation_id):
    require_approval(db, job_id)
    if db.evaluation(job_id)['id'] != evaluation_id:
        raise ValueError('The evaluation changed. Reload this application before saving the letter.')
    if not text.strip():
        raise ValueError('Enter your motivation letter before saving.')
    package = current_package(db, job_id)
    item = next(item for item in json.loads(package['plan']) if item['key'] == item_key)
    warnings = check_limits(item, text)
    if any(warning.startswith('Over ') for warning in warnings):
        raise ValueError('; '.join(warnings))
    # An edited letter has no automatically verified evidence mapping.
    return save_version(db, package, item, text.strip(), [],
                        warnings + ['User-edited motivation letter; verify personal claims and formatting before use.'], 'User edit')


def original_post(db, job, analysis):
    with st.expander('Original job post', expanded=True):
        url = job['source_url'] or next((s['url'] for s in db.sources(job['id']) if s['note'] == 'Primary advertisement'), '')
        parsed = urlsplit(url)
        if parsed.scheme in {'http', 'https'} and parsed.netloc:
            st.link_button('Open original post', url)
        else:
            st.caption('No original post link was saved for this job.')
        details = [getattr(analysis, field).value for field in ('title', 'institution', 'location')]
        if any(details):
            st.write(' · '.join(value for value in details if value))
        try:
            from office.analysis_input import inputs
            sources, _ = inputs(db, job, use_override=False)
            original = sources[0]['text']
        except (ValueError, OSError):
            original = job['original']
        with st.container(height=280):
            st.text(original)


def fit_panels(evaluation):
    criteria = json.loads(evaluation['payload']).get('criteria', []) if evaluation else []
    strengths = [row for row in criteria if row['result'] == 'satisfied']
    gaps = [row for row in criteria if row['result'] != 'satisfied']
    left, right = st.columns(2)
    for column, title, rows in ((left, 'My strengths', strengths), (right, 'Gaps and shortcomings', gaps)):
        with column, st.expander(title, expanded=True):
            if not rows:
                st.caption('No confirmed matches recorded.' if column is left else 'No gaps recorded in this evaluation.')
            for row in rows:
                # Reuse the agent's job-specific assessment, without repeating CV
                # records or making another model request whenever the page opens.
                explanation = row.get('explanation', '').strip()
                if not explanation:
                    explanation = ('Your confirmed experience meets this requirement.' if row['result'] == 'satisfied'
                                   else 'Your CV does not yet establish a full match for this requirement.')
                st.write('• ' + explanation)
                criterion = ' '.join(row['criterion'].split())
                if len(criterion) > 180:
                    criterion = criterion[:177].rsplit(' ', 1)[0] + '…'
                if row['result'] != 'satisfied':
                    label = {'partial': 'Partial match', 'not_satisfied': 'Does not match',
                             'unknown': 'Evidence needs review' if row.get('evidence') else 'Not evidenced in your CV'}.get(row['result'], 'Needs review')
                    st.caption(label + ' · ' + criterion)
                else:
                    st.caption('Matches: ' + criterion)


def motivation_editor(db, job_id, item, evaluation, draft, settings):
    with st.expander('Motivation letter', expanded=True):
        if item['kind'] == 'supporting_statement':
            st.caption('The advert asks for the letter within your supporting statement; address its selection criteria here.')
        caps = [f"{item[key]} {label}" for key, label in
                [('word_limit', 'words'), ('character_limit', 'characters'), ('page_limit', 'pages')] if item[key]]
        if caps:
            st.caption('Maximum: ' + ' · '.join(caps))
        if st.button('Regenerate motivation letter' if draft else 'Generate motivation letter', key=f'letter-generate-{job_id}'):
            try:
                current_package(db, job_id)
                with st.spinner('Preparing your letter for this job…'):
                    generate_document(db, job_id, item['key'], settings)
                st.rerun()
            except (Exception, Cancelled) as exc:
                st.error(str(exc))
        if draft:
            notes = [warning for warning in json.loads(draft['warnings']) if not warning.startswith(
                ('Draft requires', 'Fact-preserving draft:', 'User-edited'))]
            if notes:
                st.warning('Check before using this letter: ' + ' '.join(notes))
        with st.form(f'letter-edit-{job_id}-{evaluation["id"]}-{draft["id"] if draft else "new"}'):
            text = st.text_area('Motivation letter text', draft['body'] if draft else '', height=350, label_visibility='collapsed')
            if draft:
                st.caption(f"{count_words(draft['body'])} words in the saved letter")
            if st.form_submit_button('Save motivation letter'):
                try:
                    save_letter(db, job_id, item['key'], text, evaluation['id'])
                    st.session_state['application_notice'] = 'Motivation letter saved.'
                    st.rerun()
                except (Exception, Cancelled) as exc:
                    st.error(str(exc))
        if draft and Path(draft['file_path']).is_file():
            path = Path(draft['file_path'])
            st.download_button('Download motivation letter', path.read_bytes(), file_name=path.name, key=f'letter-download-{draft["id"]}')


REQUIREMENT_PREFIXES = {'document': 'Prepare this document', 'question': 'Draft an answer to this question',
                        'application': 'Complete this step manually'}


def requirement_task(db, job_id, requirement):
    text = REQUIREMENT_PREFIXES[requirement.category] + ': ' + requirement.text
    return text, next((task for task in db.tasks(job_id) if task['text'] == text and task['source'] == requirement.source_quote), None)


def remaining_requirements(db, job_id, analysis, plan, letter, latest, settings):
    st.subheader('Other requirements')
    shown = 0
    for index, requirement in enumerate(analysis.requirements):
        if requirement.category not in REQUIREMENT_PREFIXES:
            continue
        items = [item for item in plan if item['requirement_index'] == index]
        others = [item for item in items if not letter or item['key'] != letter['key']]
        if letter and items and not others:
            continue
        shown += 1
        task_text, task = requirement_task(db, job_id, requirement)
        brief = ' '.join(requirement.text.split())
        if len(brief) > 220:
            brief = brief[:217].rsplit(' ', 1)[0] + '…'
        if requirement.importance != 'mandatory':
            brief += ' (' + ('preferred' if requirement.importance == 'preferred' else 'verify requirement') + ')'
        checked = st.checkbox(brief, value=bool(task and task['complete']),
                              key=f'application-requirement-{job_id}-{index}', help=requirement.text)
        if checked != bool(task and task['complete']):
            if task:
                db.set_complete(task['id'], checked)
            else:
                with db.connect() as c:
                    c.execute('INSERT INTO tasks(job_id,text,source,verification,importance,complete) VALUES(?,?,?,?,?,?)',
                              (job_id, task_text, requirement.source_quote,
                               requirement.importance == 'unclear', requirement.importance, int(checked)))
        for item in others:
            draft = latest.get(item['key'])
            if draft and Path(draft['file_path']).is_file():
                path = Path(draft['file_path'])
                st.download_button('Download ' + item['title'].lower(), path.read_bytes(), file_name=path.name,
                                   key=f'material-download-{draft["id"]}')
    if not shown:
        st.caption('No other application materials or steps were specified.')
    missing = [item for item in plan if not item['manual'] and (not letter or item['key'] != letter['key'])
               and (item['key'] not in latest or not Path(latest[item['key']]['file_path']).is_file())]
    if missing and st.button('Prepare missing materials', key=f'materials-generate-{job_id}'):
        try:
            current_package(db, job_id)
            for item in missing:
                with st.spinner(f"Preparing {item['title'].lower()}…"):
                    generate_document(db, job_id, item['key'], settings)
            st.rerun()
        except (Exception, Cancelled) as exc:
            st.error(str(exc))


def application_page(db, job_id, settings):
    job = db.job(job_id)
    if not job['analysis']:
        st.info('Analyze this job in Job Processing first.')
        return
    analysis = Analysis.model_validate_json(job['analysis'])
    st.metric('Deadline to apply', analysis.deadline.value or 'Not specified')
    original_post(db, job, analysis)
    evaluation = db.evaluation(job_id)
    current = evaluation_current(db, job_id, evaluation)
    if not current:
        st.warning('Your CV or this job changed. Evaluate and approve it again in Job Processing.')
    fit_panels(evaluation if current else None)
    plan = plan_documents(analysis)
    letter = motivation_item(plan)
    package = db.package(job_id)
    latest = {}
    if current and package and package['evaluation_id'] == evaluation['id']:
        for draft in db.drafts(package['id']):
            latest.setdefault(draft['item_key'], draft)
    if letter and current:
        motivation_editor(db, job_id, letter, evaluation, latest.get(letter['key']), settings)
    remaining_requirements(db, job_id, analysis, plan, letter, latest, settings)
    st.divider()
    st.caption('After submitting your application, mark it as applied to move it into Application History.')
    if st.button('Applied', type='primary', key=f'application-applied-{job_id}'):
        db.set_status(job_id, 'Submitted manually')
        st.session_state['application_notice'] = 'Marked as applied. Your application and documents are saved in Application History.'
        st.rerun()
