"""Compact activity and two independent status signals: processing and fit."""
import json
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
from office.activity import snapshot
from office.decisions import decision
from office.evaluation import evaluation_current

COLOURS={'green':'#e7f4ea','yellow':'#fff4cc','red':'#fde5e5','neutral':''}
SHAPES={1:'■',2:'▲',3:'●'}
NAMES={1:'Research',2:'Evaluation',3:'Preparation'}


def duration(start,end=None):
    first=datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    last=datetime.fromisoformat(end).replace(tzinfo=timezone.utc) if end else datetime.now(timezone.utc)
    seconds=max(0,int((last-first).total_seconds()))
    return f'{seconds//3600}h {(seconds%3600)//60}m' if seconds>=3600 else f'{seconds//60}m {seconds%60:02d}s'


@st.fragment(run_every=3)
def activity_panel(db):
    import uuid
    from office.case_worker import touch,ensure_worker
    if 'office-presence-id' not in st.session_state:
        st.session_state['office-presence-id']=uuid.uuid4().hex
    touch(db,st.session_state['office-presence-id'])
    ensure_worker(db)
    active,history=snapshot(db)
    from office.control import request,state
    mode=state(db)['mode']
    st.markdown('### Agent activity')
    st.caption('Office: '+mode.title())
    if mode=='paused':
        st.caption('Pause requested. Work pauses at the next checkpoint after the current request.')
    if mode=='stopped' and active:
        st.caption('Stop requested. Waiting for the current request to return.')
    if not active and mode=='running':
        left,right=st.columns(2)
        if left.button('Pause office',key='pause-office'):
            request(db,'paused'); st.rerun()
        if right.button('Stop office',key='stop-office'):
            request(db,'stopped'); st.rerun()
    if mode in {'paused','stopped'}:
        if st.button('Resume office',key='resume-office'):
            request(db,'running')
            with db.connect() as c:
                has_worker=c.execute("SELECT 1 FROM processing_sessions WHERE heartbeat>=datetime('now','-90 seconds')").fetchone()
            # A paused worker resumes itself; a stopped worker needs a new run.
            if mode=='stopped' or not has_worker:
                from office.status_ui import launch_research
                launch_research()
            st.rerun()
    for agent in (1,2,3):
        task=next((r for r in active if r['agent']==agent),None)
        with st.container(border=True):
            st.markdown(f'**{SHAPES[agent]} Agent {agent} · {NAMES[agent]}**')
            if task:
                (st.success if mode=='running' else st.warning)(task['label'])
                status={'running':'running','paused':'paused / pausing','stopped':'stopping'}.get(mode,mode)
                st.caption(('Job #'+str(task['job_id'])+' · ' if task['job_id'] else '')+duration(task['started'])+' elapsed · '+status)
                left,right=st.columns(2)
                if left.button('Continue' if mode=='paused' else 'Pause',key=f'pause-agent-{agent}',disabled=mode not in {'running','paused'}):
                    request(db,'running' if mode=='paused' else 'paused'); st.rerun()
                if right.button('Stop',key=f'stop-agent-{agent}',disabled=mode=='stopped'):
                    request(db,'stopped'); st.rerun()
            else:
                st.caption('Idle')
            label={1:'Run extra discovery shift',2:'Process waiting jobs',3:'Prepare approved jobs'}[agent]
            if st.button(label,key=f'extra-shift-{agent}',width='stretch'):
                if mode!='running':
                    st.warning('Resume the office first.')
                else:
                    launch_research(agent=agent)
                    st.success('Shift queued; waiting for any current run to finish.')
    st.caption('Pause / Stop controls the office pipeline. The current AI/download request may finish first. Timers include waits and pauses.')
    with st.expander('Recent task history'):
        if not history:
            st.caption('No completed tasks yet.')
        for row in history[:6]:
            icon='✓' if row['state']=='completed' else '⚠'
            st.markdown(f"{SHAPES[row['agent']]} **{row['label']}**")
            st.caption(f"{icon} {row['state'].title()} · {duration(row['started'],row['finished'])}" + (f" · Job #{row['job_id']}" if row['job_id'] else ''))
    with st.expander('Task history · latest 30'):
        st.dataframe([{'Agent':SHAPES[r['agent']], 'Task':r['label'],'Job':r['job_id'],
                       'Result':r['state'],'Started (UTC)':r['started'],
                       'Duration':duration(r['started'],r['finished']),'Details':r['detail']} for r in history],hide_index=True)


def analysis_status(db,job):
    history=db.history(job['id'])
    latest=history[0] if history else None
    if latest and latest['outcome']=='stopped':
        return 'Analysis stopped — retry available','yellow'
    if latest and latest['outcome']=='running':
        with db.connect() as c:
            live=c.execute("SELECT 1 FROM agent_activity WHERE job_id=? AND label='Analyzing job requirements' AND state='running' AND heartbeat>=datetime('now','-90 seconds')",(job['id'],)).fetchone()
        return ('Analyzing','neutral') if live else ('Analysis interrupted — retry','yellow')
    if latest and latest['outcome']=='failed':
        return ('Retry failed · previous analysis retained','yellow') if job['analysis'] else ('Analysis failed','red')
    if not job['analysis']:
        return 'Pending analysis','neutral'
    from office.analysis_input import needs_refresh
    if needs_refresh(db,job['id']):
        return 'Legacy extraction · clean reanalysis needed','yellow'
    if json.loads(job.get('warnings','[]')):
        return 'Analyzed · check issues','yellow'
    return 'Analysis successful','green'


def suitability(score):
    if score is None:
        return 'Not scored','neutral'
    return ('Very suited','green') if score>=85 else (('Somewhat suited','yellow') if score>=50 else ('Least suited','red'))


def overview(db,rows):
    records=[]
    colours=[]
    scores=[]
    for row in rows:
        job=db.job(row['id'])
        analysis=json.loads(job['analysis']) if job['analysis'] else {}
        title=(analysis.get('title') or {}).get('value') or job['original'][:90]
        label,tone=analysis_status(db,job)
        evaluation=db.evaluation(job['id'])
        review=decision(db,job['id'])
        fresh=evaluation_current(db,job['id'],evaluation)
        score=(review['score'] if review else json.loads(evaluation['payload'])['score']) if fresh else None
        fit,fit_tone=suitability(score)
        if evaluation and not fresh:
            fit='Outdated — reevaluate'
            fit_tone='yellow'
        records.append({'ID':job['id'],'Job':title,'Analysis':label,'Suitability':f'{score}/100 · {fit}' if score is not None else fit,
                        'Your decision':review['decision'].title() if review else ('Awaiting review' if fresh else '—')})
        colours.append((tone,fit_tone))
        scores.append(score)
    if not records:
        st.info('No saved jobs yet.')
        return
    order=sorted(range(len(records)),key=lambda i: (scores[i] is None, -(scores[i] if scores[i] is not None else 0)))
    records=[records[i] for i in order]
    colours=[colours[i] for i in order]
    frame=pd.DataFrame(records)
    def style(row):
        base,fit=colours[row.name]
        return [f'background-color: {COLOURS[fit if col=="Suitability" else base]}; color: #17251b' if COLOURS[fit if col=='Suitability' else base] else '' for col in row.index]
    st.dataframe(frame.style.apply(style,axis=1),hide_index=True,width='stretch')
    st.caption('Analysis: green = successful, yellow = review issues, red = failed; pending stays neutral. Suitability: green ≥85, yellow 50–84, red <50. Colours also have text labels.')


def launch_research(approved_only=False, agent=None):
    import subprocess
    import sys
    import os
    from office.config import ROOT,DATA
    with (DATA/'background-office.log').open('a',encoding='utf-8') as log:
        subprocess.Popen([sys.executable,str(ROOT/'scripts/run_office.py'),'--wait','--parent-pid',str(os.getpid())]+(['--approved-only'] if approved_only else [])+(['--agent',str(agent)] if agent else []),cwd=ROOT,
                         stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)


def launch_approved():
    launch_research(True)
