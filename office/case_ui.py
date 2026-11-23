import json
import streamlit as st
from office.evaluation import evaluation_current
from office.decisions import decision,save_decision


def preparation_board(db):
    st.subheader('● Agent 3 · Cases to prepare')
    st.caption('Approved cases are shown here. Untick a case to return it to Job Processing. A changed analysis or profile requires a fresh evaluation and approval.')
    groups=[[],[],[]]
    from office.navigation import selected_jobs, rejected_ids
    rejected = rejected_ids(db)
    for job in selected_jobs(db):
        evaluation=db.evaluation(job['id'])
        if not evaluation_current(db,job['id'],evaluation):
            continue
        if job['status'] in {'Rejected','Withdrawn','Submitted manually','Interview','Offer'}:
            continue
        payload=json.loads(evaluation['payload']);review=decision(db,job['id'])
        score=review['score'] if review else payload['score']
        if score is None:
            continue
        groups[0 if score>=85 else 1 if score>=50 else 2].append((job,evaluation,score,review))
    for title,entries in zip(['🟢 Very suited · 85–100','🟡 Somewhat suited · 50–84','🔴 Least suited · 0–49'],groups):
        with st.expander(f'{title} ({len(entries)})',expanded=True):
            if not entries:
                st.caption('No evaluated cases in this group yet.')
            for job,evaluation,score,review in entries:
                analysis=json.loads(job['analysis'])
                name=analysis['title']['value'] or f'Job #{job["id"]}'
                selected=bool(review and review['decision']=='approved')
                value=st.checkbox(f'#{job["id"]} · {name} · {score}/100',value=selected,key=f'prepare-case-{job["id"]}-{evaluation["id"]}')
                if value!=selected:
                    try:
                        save_decision(db,job['id'],evaluation['id'],score,'approved' if value else 'waiting',review['note'] if review else '')
                        st.success('Preparation selected.' if value else 'Preparation put on hold.')
                    except Exception as exc:
                        st.error(str(exc))
    with db.connect() as c:
        issues=[dict(r) for r in c.execute("SELECT job_id AS 'Case',stage AS 'Stage',issue AS 'Needs your attention' FROM case_state WHERE stage='needs_review' OR (evaluation_dirty=1 AND issue!='') ORDER BY job_id")]
        unscored=[dict(r) for r in c.execute("SELECT j.id AS 'Case' FROM jobs j JOIN evaluations e ON e.id=(SELECT MAX(id) FROM evaluations WHERE job_id=j.id) WHERE json_extract(e.payload,'$.score') IS NULL")]
    issues = [row for row in issues if row['Case'] not in rejected]
    unscored = [row for row in unscored if row['Case'] not in rejected]
    with st.expander(f'Cases needing attention ({len(issues)})',expanded=bool(issues)):
        if issues:
            st.dataframe(issues,hide_index=True)
        else:
            st.caption('No unresolved case issues.')
        if unscored:
            st.caption('These cases were evaluated but have no scorable criteria; verify their requirements:')
            st.dataframe(unscored,hide_index=True)


def evidence_and_edit(db,job):
    from office.analysis_input import inputs
    from office.cases import correct_text
    job_id=job['id']
    try:
        sources,title=inputs(db,job)
        clean='\n\n'.join(item['text'] for item in sources)
    except Exception as exc:
        clean=''
        st.error(f'This case needs source isolation: {exc}')
    with st.expander('Correct this case and reprocess'):
        st.caption('Use only this vacancy’s complete text. Saving archives the current analysis/review, then queues extraction and evaluation. Original downloads and old evaluations remain available.')
        with st.form(f'correct-case-{job_id}'):
            text=st.text_area('Correct advertisement text',value=clean,height=280)
            confirmed=st.checkbox('I checked this text against the target vacancy')
            if st.form_submit_button('Save correction and queue evaluation'):
                if not confirmed:
                    st.error('Check the source and confirm the correction first.')
                else:
                    try:
                        correct_text(db,job_id,text);st.success('Case revision saved. Agent 2 will reprocess it when the office is running.')
                    except Exception as exc:
                        st.error(str(exc))


def case_extras(db, job):
    from office.cases import delete_case
    job_id = job['id']
    with st.expander('Cleaning preview'):
        try:
            from office.analysis_input import inputs
            sources,title=inputs(db,job,use_override=False)
            cleaned='\n\n'.join(source['text'] for source in sources)
            st.caption(f"Original: {len(job['original']):,} characters · Cleaned: {len(cleaned):,} characters")
            st.caption('Navigation and unrelated linked documents excluded. Original downloads remain stored. Review completeness before using this text.')
            st.text(cleaned)
            for source in sources:
                st.text(source['url'])
            if st.button('Use this cleaned text and queue reanalysis',key=f'clean-case-{job_id}'):
                from office.cases import correct_text
                correct_text(db,job_id,cleaned)
                st.success('Previous analysis archived; cleaned text queued for reanalysis.')
        except Exception as exc:
            st.warning(str(exc))
    with st.expander('Delete this case · allow rediscovery'):
        st.caption('Deletes this case and its database history, including discovery/deduplication memory. Exported files remain on disk. Stop the office first. The next source scan can find the vacancy again.')
        confirmed=st.checkbox('Delete this case and forget that it was discovered',key=f'delete-case-confirm-{job_id}')
        if st.button('Delete case and allow rediscovery',disabled=not confirmed,key=f'delete-case-{job_id}'):
            try:
                delete_case(db,job_id);st.session_state.pop('selected_job',None);st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with st.expander('Previous case revisions'):
        with db.connect() as c:
            rows=[dict(r) for r in c.execute('SELECT * FROM case_revisions WHERE job_id=? ORDER BY id DESC',(job_id,))]
        for row in rows:
            st.caption(row['created']+' UTC · '+row['reason']);st.json(json.loads(row['snapshot']),expanded=False)
