import json
import subprocess
import sys
import streamlit as st
from office.config import ROOT, DATA
from office.autonomous import config, initialize, OfficeSettings


def office_page(db):
    initialize(db)
    st.subheader('Autonomous Office')
    st.caption('Research, requirements and draft preparation. All applications require your review and manual submission.')
    st.info('Manual start only. Agents run while this system is open; closing its PowerShell window stops the workers. Scheduled startup is disabled.')
    st.button('Refresh activity')
    with db.connect() as conn:
        runs = [dict(r) for r in conn.execute('SELECT * FROM office_runs ORDER BY id DESC LIMIT 20')]
        events = [dict(r) for r in conn.execute('SELECT * FROM office_events ORDER BY id DESC LIMIT 100')]
        queue = [dict(r) for r in conn.execute('SELECT * FROM office_queue ORDER BY discovered DESC')]
    if runs:
        st.text('Latest run: '+runs[0]['state']+' · '+runs[0]['started']+' UTC')
        successful=next((r for r in runs if r['state']=='completed'),None)
        st.text('Last run without errors: '+(successful['finished']+' UTC' if successful else 'None yet; see source and processing errors below.'))
        if runs[0]['report']:
            report=json.loads(runs[0]['report'])
            columns=st.columns(4)
            for column,label,key in zip(columns,
                    ['New jobs','Qualifying jobs','Packages prepared','Awaiting review'],
                    ['discovered','relevant','prepared','applications_awaiting_review']):
                column.metric(label,report.get(key,0))
            if report.get('limited_run'):
                st.caption('This was a limited development smoke run, not a full daily run.')
            with st.expander('Detailed run report'):
                st.json(report)
    else:
        st.info('No background runs yet.')
    from office.status_ui import overview
    st.subheader('Jobs and decisions')
    from office.navigation import visible_jobs, rejected_ids, processing_jobs
    overview(db,processing_jobs(db))
    rejected = rejected_ids(db)
    queue = [row for row in queue if row["job_id"] not in rejected]
    from office.case_ui import preparation_board
    preparation_board(db)
    st.caption('Review a score in Job Processing → Evaluation. Approve it to start preparation; no documents are generated before approval.')
    with st.expander('Discovery queue and retrieval issues'):
        st.dataframe(queue,hide_index=True,width='stretch')
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from dateparser import parse
    today=datetime.now(ZoneInfo(config().timezone)).date()
    deadlines=[]
    from office.models import Analysis
    for job in visible_jobs(db):
        if job['analysis'] and job['status'] not in {'Rejected','Withdrawn','Submitted manually'}:
            analysis=Analysis.model_validate_json(job['analysis'])
            date=parse(analysis.deadline.value or '',settings={'STRICT_PARSING':True})
            if date and today<=date.date()<=today+timedelta(days=14):
                deadlines.append({'Job':job['id'],'Title':analysis.title.value,'Deadline':analysis.deadline.value})
    st.subheader('Deadlines in the next 14 days')
    st.dataframe(deadlines,hide_index=True,width='stretch')
    st.caption('Open Job Processing for details and evaluation, or Applications for your letter, materials and application status.')
    with st.expander('Agent activity',expanded=True):
        st.dataframe(events,hide_index=True,width='stretch')
    settings = config()
    with st.form('office-settings'):
        st.subheader('Office configuration')
        time = settings.time  # Retained for compatibility; scheduling is disabled.
        timezone = st.text_input('Time zone',settings.timezone)
        threshold = st.number_input('Minimum drafting score',0,100,settings.threshold)
        maximum = st.number_input('Maximum packages per run',0,50,settings.max_packages)
        include_studentships=st.checkbox('Include PhD studentships / doctoral student positions',value=settings.include_studentships)
        regions = st.text_input('Target countries (comma separated)',', '.join(settings.regions))
        st.caption('Leave countries empty for no country preference. Set your time zone for deadline checks.')
        st.caption('Manage recruitment websites on the Sources page.')
        if st.form_submit_button('Save office settings'):
            try:
                from datetime import datetime
                from zoneinfo import ZoneInfo
                datetime.strptime(time,'%H:%M'); ZoneInfo(timezone)
                value = OfficeSettings(time=time,timezone=timezone,threshold=int(threshold),max_packages=int(maximum),include_studentships=include_studentships,regions=[r.strip() for r in regions.split(',') if r.strip()],sources=config().sources)
                (DATA/'autonomous.json').write_text(value.model_dump_json(indent=2),encoding='utf-8')
                st.success('Configuration saved. The running office reads it on its next case.')
            except Exception as exc:
                st.error(str(exc))
