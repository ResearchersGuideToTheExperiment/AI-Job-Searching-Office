import json
from pathlib import Path
import streamlit as st
from office.config import DATA, Settings, load_settings, save_settings
from office.db import Database
from office.ingest import read_upload
from office.models import Analysis, FACT_FIELDS
from office.ollama import OllamaClient
from office.service import analyze_job
from office.profile_ui import profile_page
from office.workflow_ui import review_sources, evaluation_page, history_page
from office.application_ui import application_page
from office.retrieval import import_url
from office.local_files import sync_local_files
from office.autonomous_ui import office_page
from office.status_ui import activity_panel, overview, analysis_status
from office.control import Cancelled
from office.maintenance import maintenance_page
from office.navigation import visible_jobs, rejected_ids, processing_jobs, selected_jobs

st.set_page_config(page_title="Local Job Application Office", layout="wide")
st.title("Local Job Application Office")
st.caption("Preparation only · Local Ollama · Review and submit every application yourself")
db = Database(DATA / "office.sqlite3")
for import_note in sync_local_files(db):
    st.info(import_note)
try:
    settings = load_settings()
except (ValueError, OSError) as exc:
    st.warning(f"Could not load settings; using defaults. Save corrected settings below. {exc}")
    settings = Settings()

page = st.sidebar.radio("Workspace", ["Autonomous Office", "My Profile", "Sources", "Add Job", "Job Processing", "Applications", "Settings"], index=0)
with st.sidebar:
    activity_panel(db)


def run_analysis(job_id):
    try:
        with st.spinner("Analyzing locally. This may take several minutes…"):
            analyze_job(db, job_id, settings)
        from office.evaluation import evaluate_job
        with st.spinner('Evaluating suitability against your confirmed profile…'):
            evaluate_job(db,job_id,settings,automatic=True)
        st.success("Analysis saved. Review the evidence and checklist.")
    except (Exception,Cancelled) as exc:
        st.error(str(exc))
        st.info("The original is saved. Open Job Processing to retry; processing history contains the failure.")


def job_label(row):
    analysis = json.loads(row['analysis']) if row['analysis'] else {}
    title = (analysis.get('title') or {}).get('value') or row['preview']
    from office.evaluation import evaluation_current
    from office.decisions import decision
    evaluation = db.evaluation(row['id'])
    score = None
    if evaluation_current(db, row['id'], evaluation):
        review = decision(db, row['id'])
        score = review['score'] if review else json.loads(evaluation['payload'])['score']
    prefix = str(score) if score is not None else '—'
    return f"{prefix} · #{row['id']} · {title[:90]} · {row['status']}"


def rejected_jobs_view():
    with st.expander('Rejected jobs', expanded=False):
        rejected = rejected_ids(db)
        archived = [row for row in db.jobs() if row['id'] in rejected]
        if not archived:
            st.caption('No rejected jobs.')
        else:
            rejected_id = st.selectbox('Select a rejected job', [row['id'] for row in archived],
                format_func={row['id']: job_label(row) for row in archived}.get, key='rejected_job')
            archived_job = db.job(rejected_id)
            if archived_job['analysis']:
                extracted = Analysis.model_validate_json(archived_job['analysis'])
                st.dataframe([{'Field': field.replace('_',' ').title(),
                    'Job information': getattr(extracted,field).value or 'Unknown',
                    'Source evidence (verbatim)': getattr(extracted,field).source_quote or 'Not provided'}
                    for field in FACT_FIELDS], hide_index=True, width='stretch')
            history_page(db,rejected_id)



if page == 'Autonomous Office':
    office_page(db)
elif page == 'Sources':
    from office.source_ui import sources_page
    sources_page(db)
elif page == 'My Profile':
    profile_page(db, settings)
elif page == "Settings":
    section=st.radio('Settings section',['General','Data Management','Application History'],horizontal=True)
    if section=='Data Management':
        maintenance_page(db)
    elif section=='Application History':
        st.subheader('All job history')
        st.caption('All discovered cases remain here for reference and duplicate prevention, including selected and completed cases. Rejected cases are in Job Processing → Extras → Rejected jobs.')
        rows=visible_jobs(db)
        overview(db,rows)
        if rows:
            history_id=st.selectbox('Select a case', [r['id'] for r in rows],format_func={r['id']:job_label(r) for r in rows}.get,key='history_job')
            history_page(db,history_id)
    else:
        st.subheader("Local inference settings")
        with st.form("settings"):
            url = st.text_input("Ollama API URL (local only)", settings.api_url)
            model = st.text_input("Installed model name", settings.model)
            timeout = st.number_input("Request timeout (seconds)", 30, 900, settings.timeout_seconds)
            if st.form_submit_button("Save settings"):
                try:
                    settings = Settings(api_url=url, model=model, timeout_seconds=int(timeout))
                    save_settings(settings)
                    st.success("Settings saved.")
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
        if st.button("Test saved connection"):
            try:
                st.success(OllamaClient(settings).test_connection())
            except (Exception,Cancelled) as exc:
                st.error(str(exc))
        st.caption(f"Local storage: {DATA}")
        st.write("One inference call runs at a time within this dashboard process. Run only one dashboard instance. Only public job URL retrieval uses the internet. No cloud AI, account creation, email sending, form filling or automated submission is implemented.")

elif page == "Add Job":
    st.subheader("Add an advertisement")
    st.caption("Import a public URL, paste text, or upload a PDF/DOCX/TXT file. Originals are retained. Long advertisements are processed sequentially in overlapping sections. Scanned PDFs need a text alternative.")
    mode = st.radio('Import method', ['Job URL', 'Paste advertisement', 'Upload document'])
    with st.form("add_job"):
        job_url = st.text_input('Job advertisement URL (retrieved only in Job URL mode)')
        pasted = st.text_area("Advertisement text", height=300)
        upload = st.file_uploader("Or upload an advertisement", type=["pdf", "docx", "txt"])
        source = st.text_input("Source URL (optional reference only)",
                               help="This does not download the advertisement. Paste the job description above or upload a PDF/TXT file; you may also include its URL here.")
        submitted = st.form_submit_button("Save and analyze")
    if submitted:
        try:
            if mode == 'Job URL':
                if not job_url.strip():
                    raise ValueError('Enter the job advertisement URL above, or select a different import method.')
                with st.spinner('Retrieving public advertisement and linked PDFs…'):
                    job_id, retrieval_warnings = import_url(db, job_url.strip())
                for warning in retrieval_warnings:
                    st.warning(warning)
            elif mode == 'Paste advertisement':
                if not pasted.strip():
                    raise ValueError('Paste the advertisement text before saving.')
                job_id = db.add_job(pasted, source)
            else:
                if upload is None:
                    raise ValueError('Choose a PDF, DOCX or TXT file before saving.')
                content = upload.getvalue()
                original = read_upload(upload.name, content)
                job_id = db.add_job(original, source, upload.name, content)
            st.session_state['selected_job'] = job_id
            st.success(f"Original saved as job #{job_id}.")
            run_analysis(job_id)
        except (Exception,Cancelled) as exc:
            st.error(str(exc))

else:
    if page == 'Applications' and 'application_notice' in st.session_state:
        st.success(st.session_state.pop('application_notice'))
    rows = processing_jobs(db) if page == 'Job Processing' else selected_jobs(db)
    if not rows:
        st.info("No selected applications. Select a case for Agent 3 first." if page == 'Applications' else "No jobs awaiting processing. Approved jobs are in Applications; rejected jobs are in Extras.")
        if page == 'Job Processing':
            with st.expander('Extras', expanded=False):
                rejected_jobs_view()
        st.stop()
    if page == "Job Processing":
        st.subheader("Job Processing")
        overview(db,rows)
    ids = [r['id'] for r in rows]
    labels = {r['id']: job_label(r) for r in rows}
    if st.session_state.get('selected_job') not in ids:
        st.session_state['selected_job'] = ids[0]
    job_id = st.selectbox("Select a saved job", ids, format_func=labels.get, key="selected_job")
    if page == 'Job Processing':
        from office.workflow_ui import job_actions
        job_actions(db,job_id)
    job = db.job(job_id)
    analysis = Analysis.model_validate_json(job['analysis']) if job['analysis'] else None
    if page == 'Job Processing':
        status_text,status_tone=analysis_status(db,job)
        {'green':st.success,'yellow':st.warning,'red':st.error,'neutral':st.info}[status_tone](status_text)
        details_tab,evaluation_tab=st.tabs(['Job details','Evaluation'])
        with evaluation_tab:
            evaluation_page(db,job_id,settings)
        with details_tab:
            if not analysis:
                st.info('This advertisement has not been successfully analyzed.')
            else:
                warnings=json.loads(job['warnings'])
                if warnings:
                    with st.expander(f'Analysis issues ({len(warnings)})'):
                        for warning in warnings:
                            st.warning(warning)
                st.dataframe([{'Field':field.replace('_',' ').title(),
                               'Job information':getattr(analysis,field).value or 'Unknown',
                               'Source evidence (verbatim)':getattr(analysis,field).source_quote or 'Not provided'}
                              for field in FACT_FIELDS],hide_index=True,width='stretch')
                if analysis.requirements:
                    with st.expander('Employer requirements'):
                        st.dataframe([r.model_dump() for r in analysis.requirements],hide_index=True,width='stretch')
            review_sources(db, job_id, analysis)
            from office.case_ui import evidence_and_edit, case_extras
            evidence_and_edit(db,job)
            with db.connect() as connection:
                reviewed = bool(connection.execute('SELECT 1 FROM analysis_reviews WHERE job_id=?', (job_id,)).fetchone())
            replace_ok = not analysis
            if reviewed:
                st.caption('This analysis is reviewed and protected. Use Correct this case to revise it, or create a separate copy in Extras.')
            elif analysis:
                replace_ok = st.checkbox("Replace existing analysis (unchanged checklist tasks retain completion)", key=f"replace-{job_id}")
                if not replace_ok:
                    st.caption('Analysis is already saved. Tick Replace existing analysis above to enable another analysis.')
            if st.button("Analyze / retry analysis", disabled=reviewed or not replace_ok):
                run_analysis(job_id)
                st.rerun()
            with st.expander('Extras', expanded=False):
                rejected_jobs_view()
                case_extras(db,job)
                if analysis and st.button('Create separate copy for clean reanalysis'):
                    copied=db.copy_job_for_reanalysis(job_id)
                    st.success(f'Created job #{copied}. Select it above and analyze it. This job and its reviews are unchanged.')
                with st.expander("AI processing history"):
                    for run in db.history(job_id):
                        st.json(run, expanded=False)
                with st.expander("Raw original capture · audit only (may include unrelated site content)"):
                    st.text(job['original'])
                    st.download_button("Download original text", job['original'], file_name=f"job-{job_id}-original.txt", mime="text/plain")
                    if job['original_file'] is not None:
                        st.download_button("Download original uploaded file", job['original_file'], file_name=Path(job['filename']).name)

    if page == 'Applications':
        application_page(db, job_id, settings)

