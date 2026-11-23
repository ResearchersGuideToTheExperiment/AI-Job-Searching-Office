import json
from pathlib import Path
import streamlit as st
from office.models import Analysis
from office.evaluation import evaluate_job, evaluation_current, analysis_fingerprint
from office.decisions import decision, save_decision
from office.status_ui import suitability, launch_approved
from office.control import Cancelled


def review_sources(db, job_id, analysis):
    sources = db.sources(job_id)
    for source in sources:
        url = source['url']
        if url.startswith(('https://', 'http://')):
            st.link_button(url, url)
        else:
            st.text(url)
        st.caption(f"Retrieved: {source['retrieved_at']} UTC")
    if not sources and db.job(job_id)['source_url']:
        st.text(db.job(job_id)['source_url'])
    if analysis:
        digest = analysis_fingerprint(analysis)
        if db.is_analysis_reviewed(job_id, digest):
            st.success('This extraction has been marked reviewed by you.')
        else:
            st.info('Review the extracted information against the source. Use Correct this case below if anything needs changing; evaluation can proceed independently.')
            if st.checkbox('I have checked the extracted criteria and application requirements against the source', key=f'review-{job_id}'):
                if st.button('Confirm job review'):
                    db.review_analysis(job_id, digest)
                    st.rerun()


def job_actions(db, job_id):
    st.markdown("""<style>
    .st-key-case-approve button {background-color:#16763b;color:white;border-color:#16763b;}
    .st-key-case-reject button {background-color:#b4232d;color:white;border-color:#b4232d;}
    </style>""", unsafe_allow_html=True)
    left, right = st.columns(2)
    with left, st.container(key='case-approve'):
        approve = st.button('Approve for preparation', width='stretch')
    with right, st.container(key='case-reject'):
        reject = st.button('Reject job', width='stretch')
    if not (approve or reject):
        return
    try:
        evaluation = db.evaluation(job_id)
        current = evaluation_current(db,job_id,evaluation)
        if approve and not current:
            st.warning('A current suitability evaluation is required. Open Evaluation below and evaluate this job first; resolve any extraction issue shown there.')
            return
        if approve and db.job(job_id)['status'] in {'Rejected','Withdrawn','Submitted manually','Interview','Offer'}:
            st.warning('This case is closed and cannot be approved for preparation.')
            return
        if current:
            review = decision(db,job_id)
            score = review['score'] if review else json.loads(evaluation['payload'])['score']
            if approve and score is None:
                st.warning('This job has no scorable criteria. Correct its requirements and evaluate it, or save your reviewed score with a reason in Evaluation.')
                return
            if score is None:
                db.set_status(job_id,'Rejected')
            else:
                save_decision(db,job_id,evaluation['id'],score,'approved' if approve else 'rejected',review['note'] if review else '')
        else:
            db.set_status(job_id,'Rejected')
        if approve:
            launch_approved()
            st.rerun()
        else:
            st.rerun()
    except (Exception,Cancelled) as exc:
        st.warning(str(exc))


def evaluation_page(db, job_id, settings):
    st.subheader('Job Evaluation')
    st.caption('Unknown salary or application email does not block suitability scoring. Identity or source-isolation failures require correction first.')
    from office.analysis_input import needs_refresh
    refresh_needed = needs_refresh(db, job_id)
    if refresh_needed:
        st.warning('Evaluation needs a fresh extraction using the current webpage cleaner. This is separate from your evidence review: the stored extraction predates the current cleaning checks.')
        st.info('In Job details, use Correct this case to save the verified complete advertisement and queue reprocessing, or open Extras and create a separate copy for clean reanalysis. Your reviewed version is preserved.')
    if st.button('Evaluate against my confirmed profile', disabled=refresh_needed):
        try:
            with st.spinner('Comparing criteria with confirmed career facts…'):
                message = st.empty()
                evaluate_job(db, job_id, settings, message.text, automatic=True)
            st.success('Evaluation saved.')
        except (Exception,Cancelled) as exc:
            st.error(str(exc))
    evaluation = db.evaluation(job_id)
    if not evaluation:
        if not refresh_needed:
            st.info('New jobs are evaluated automatically. For an older saved job, use Evaluate above after confirming your profile facts.')
        return
    if not evaluation_current(db, job_id, evaluation):
        st.warning('This evaluation is outdated because the profile or job extraction changed. Evaluate again before generating documents.')
    payload = json.loads(evaluation['payload'])
    review=decision(db,job_id)
    display_score=review['score'] if review else payload['score']
    fit,tone=suitability(display_score)
    {'green':st.success,'yellow':st.warning,'red':st.error,'neutral':st.info}[tone](f'{fit} · {display_score}/100' if display_score is not None else fit)
    st.caption('AI score is preserved below. Your corrections and approval are stored separately. Approval allows preparation even if you choose to pursue a lower-scoring job.')
    if review:
        st.info(f"Your decision: {review['decision']} · {review['score']}/100. {review['note']}")
    with st.form(f'evaluation-review-{evaluation["id"]}'):
        score=st.number_input('Your reviewed suitability score',0,100,int(display_score or 0))
        note=st.text_area('Correction / review notes',value=review['note'] if review else '',help='Explain a changed score or any eligibility concern you have resolved.')
        save_review=st.form_submit_button('Save score and notes')
    if save_review:
        try:
            save_decision(db,job_id,evaluation['id'],int(score),review['decision'] if review else 'waiting',note)
            st.success('Score and notes saved.')
        except (Exception,Cancelled) as exc:
            st.warning(str(exc))
    st.metric('Evidence-based suitability', f"{payload['score']}/100" if payload['score'] is not None else 'Not scorable — no criteria extracted')
    st.caption(payload['formula'])
    st.info(payload['note'])
    st.text(f"Unknown requirements: {payload['unknown_count']}")
    for group, label in [('eligibility','Employer eligibility requirements'), ('essential','Employer-essential criteria'), ('desirable','Employer-preferred criteria')]:
        rows = [row for row in payload['criteria'] if row['category'] == group]
        if not rows:
            continue
        st.subheader(label)
        st.dataframe([{'Employer criterion': row['criterion'],
                       'Assessment': row['result'].replace('_', ' ').title(),
                       'Reason': row['explanation'],
                       'Advertisement evidence': row['source_quote'],
                       'Eligibility concern': row['eligibility_concern'] or ''}
                      for row in rows], hide_index=True, width='stretch')


def history_page(db, job_id):
    st.subheader('Application History')
    st.text(f"Case status: {db.job(job_id)['status']}")
    with db.connect() as conn:
        packages = [dict(r) for r in conn.execute('SELECT * FROM packages WHERE job_id=? ORDER BY id DESC', (job_id,))]
    for package in packages:
        with st.expander(f"Package #{package['id']} · {package['created_at']} UTC"):
            for draft in db.drafts(package['id']):
                st.text(f"{draft['title']} v{draft['version']} · {draft['origin']}")
                path = Path(draft['file_path'])
                if path.exists():
                    st.download_button('Download version', path.read_bytes(), file_name=path.name, key=f"history-draft-{draft['id']}")
    with st.expander('AI processing operations'):
        st.json(db.operations(job_id))
