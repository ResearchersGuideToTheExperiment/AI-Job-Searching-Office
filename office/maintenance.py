"""Explicit section cleanup, with worker exclusion and confined file deletion."""
from pathlib import Path

SECTIONS={
    'jobs':'All saved jobs, originals, evaluations, approvals, checklists, packages and discovery queue',
    'packages':'Application packages and generated document versions (keeps jobs and evaluations)',
    'evaluations':'Evaluations and approvals, plus dependent application packages',
    'checklists':'All application checklist items and completion marks',
    'history':'Processing, agent activity and research-run history (keeps jobs and documents)',
    'discovery':'Discovery queue (jobs may be discovered again)',
    'profile':'Imported CV copies and career facts, including confirmations (keeps files in cv/)',
    'preferences':'Saved writing style and job preferences (keeps Markdown source files)',
}


def counts(db):
    with db.connect() as c:
        return {name:c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for name,table in
                [('Jobs','jobs'),('Evaluations','evaluations'),('Draft versions','drafts'),
                 ('Checklist items','tasks'),('Career facts','profile_facts'),('Activity records','agent_activity')]}


def clear_sections(db,sections,remove_files=True):
    selected=set(sections)
    if not selected or selected-set(SECTIONS):
        raise ValueError('Select valid sections to clear.')
    files=[]
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT mode FROM office_control WHERE id=1').fetchone()[0]!='stopped':
            raise ValueError('Stop the office before clearing data.')
        if c.execute("SELECT 1 FROM processing_sessions WHERE heartbeat>=datetime('now','-90 seconds')").fetchone():
            raise ValueError('A worker is still finishing its current request. Wait until it stops.')
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'office_runs' in tables and c.execute("SELECT 1 FROM office_runs WHERE state='running'").fetchone():
            raise ValueError('A research run is still active. Wait for it to stop before clearing data.')
        c.execute("UPDATE office_control SET mode='cleaning' WHERE id=1")
        if selected & {'jobs','evaluations','packages'}:
            if remove_files:
                root=db.path.parent/'applications'
                if root.resolve()!=root:
                    raise ValueError('The applications folder is redirected; file cleanup refused.')
                for row in c.execute('SELECT file_path FROM drafts'):
                    path=Path(row[0])
                    if not path.resolve().is_relative_to(root) or path.is_symlink():
                        raise ValueError('A draft path points outside the application folder; file cleanup refused.')
                    files.append(path)
            c.execute('DELETE FROM drafts'); c.execute('DELETE FROM packages')
        if selected & {'jobs','evaluations'}:
            c.execute('DELETE FROM evaluation_steps')
            c.execute('DELETE FROM evaluation_decisions'); c.execute('DELETE FROM evaluations')
        if selected & {'jobs','checklists'}:
            c.execute('DELETE FROM tasks')
        if 'jobs' in selected:
            c.execute('DELETE FROM extraction_cache')
            c.execute('DELETE FROM evaluation_steps')
            c.execute('DELETE FROM case_state');c.execute('DELETE FROM case_revisions');c.execute('DELETE FROM inference_metrics WHERE job_id IS NOT NULL')
            c.execute('DELETE FROM analysis_evidence');c.execute('DELETE FROM analysis_inputs')
            for table in ('requirements','sources','analysis_reviews','history'):
                c.execute(f'DELETE FROM {table}')
            c.execute('DELETE FROM operations WHERE job_id IS NOT NULL')
            c.execute('DELETE FROM agent_activity WHERE job_id IS NOT NULL')
            c.execute('DELETE FROM jobs')
        if selected & {'jobs','discovery'} and 'office_queue' in tables:
            c.execute('DELETE FROM office_queue')
            c.execute('UPDATE office_worker SET discovered=NULL WHERE id=1')
        elif selected & {'evaluations','packages'} and 'office_queue' in tables:
            c.execute("UPDATE office_queue SET state='assessed' WHERE state IN ('prepared_review_required','manual_materials_required','awaiting_approval')")
        if 'history' in selected:
            for table in ('history','operations','agent_activity','office_events','office_runs','analysis_inputs','analysis_evidence','inference_metrics','extraction_cache','evaluation_steps'):
                if table in tables:
                    c.execute(f'DELETE FROM {table}')
        if 'profile' in selected:
            c.execute('DELETE FROM profile_facts'); c.execute('DELETE FROM profile_documents')
            if 'local_imports' in tables:
                c.execute('UPDATE local_imports SET document_id=NULL WHERE document_id IS NOT NULL')
        if 'preferences' in selected:
            c.execute("UPDATE preferences SET style='',preferences='' WHERE id=1")
    errors=[]
    try:
        for path in set(files):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                errors.append(f'Could not remove {path.name}: {exc}')
    finally:
        with db.connect() as c:
            c.execute("UPDATE office_control SET mode='stopped' WHERE id=1")
    return errors


def maintenance_page(db):
    import streamlit as st
    from office.control import request,state
    st.subheader('Data Management')
    st.write('Clear selected sections from this computer. This cannot be undone. Settings, the AI model and source files stay in place.')
    columns=st.columns(3)
    for index,(label,count) in enumerate(counts(db).items()):
        columns[index%3].metric(label,count)
    if st.button('Stop office for cleanup'):
        request(db,'stopped')
        st.rerun()
    st.caption('Office: '+state(db)['mode']+'. Wait for active work to stop before clearing data. It stays stopped after cleanup.')
    with st.form('clear-data'):
        selected=st.multiselect('Sections to clear',list(SECTIONS),format_func=lambda key:SECTIONS[key])
        files=st.checkbox('Also delete generated DOCX files for cleared packages',value=True)
        confirmed=st.checkbox('I understand that the selected data will be permanently removed')
        submitted=st.form_submit_button('Clear selected data',type='primary')
    if submitted:
        if not confirmed or not selected:
            st.error('Select sections and confirm deletion first.')
            return
        try:
            errors=clear_sections(db,selected,files)
            st.session_state.pop('selected_job',None)
            st.success('Selected data cleared. The office remains stopped.')
            for error in errors:
                st.warning(error)
        except Exception as exc:
            st.error(str(exc))
