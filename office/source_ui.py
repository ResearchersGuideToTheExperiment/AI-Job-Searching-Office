"""Editable approved sources and explicit approval of discovered candidates."""
import json
import re
from urllib.parse import urlsplit
import streamlit as st
from office.config import DATA
from office.autonomous import config


def save_sources(rows):
    result=[];seen=set()
    for row in rows:
        url=str(row.get('url') or '').strip();name=str(row.get('name') or '').strip()
        pattern=str(row.get('pattern') or '').strip()
        if not url and not name: continue
        parts=urlsplit(url)
        if not name or parts.scheme not in {'http','https'} or not parts.hostname:
            raise ValueError('Each source needs a name and a public listing URL.')
        if pattern: re.compile(pattern)
        if url in seen or name in {s['name'] for s in result}:
            raise ValueError('Source names and URLs must be unique.')
        seen.add(url);result.append(dict(name=name,url=url,pattern=pattern,enabled=bool(row.get('enabled',True))))
    settings=config();settings.sources=result
    DATA.mkdir(parents=True, exist_ok=True)
    path=DATA/'autonomous.json';temporary=path.with_suffix('.tmp')
    temporary.write_text(settings.model_dump_json(indent=2),encoding='utf-8');temporary.replace(path)


def sources_page(db):
    from office.autonomous import initialize
    initialize(db)
    st.subheader('Sources')
    if not config().sources:
        st.info('Add a public job-listing website below to enable discovery, or import an individual vacancy on Add Job.')
    st.caption('Add rows to add sources; select rows to delete them. Disable a source to pause searches there. Changes apply on the next run.')
    st.caption('Enter a name and the vacancy-listing URL. Individual job links are detected automatically; some websites may need additional support.')
    existing={row['url']:row for row in config().sources}
    import pandas as pd
    with st.form('sources-editor'):
        rows=st.data_editor(pd.DataFrame(config().sources,columns=['name','url','enabled']),num_rows='dynamic',hide_index=True,width='stretch',column_config={'enabled':st.column_config.CheckboxColumn('Enabled')})
        if st.form_submit_button('Save sources'):
            try:
                values=rows.fillna('').to_dict('records')
                for value in values:
                    value['pattern']=existing.get(value['url'],{}).get('pattern','')
                save_sources(values);st.success('Sources saved. New sources use automatic link detection.')
            except Exception as exc: st.error(str(exc))
    st.subheader('Suggested sources')
    st.caption('Agent 1 finds candidate recruitment links while scanning approved sources. Candidates are unverified and are never searched as sources until you approve them.')
    with db.connect() as c:
        candidates=[dict(r) for r in c.execute("SELECT * FROM source_suggestions WHERE state='pending' ORDER BY created DESC")]
    if not candidates: st.info('No suggestions yet. Run Agent 1 for an extra discovery shift.')
    for row in candidates:
        with st.expander(row['name']):
            st.link_button('Open candidate website',row['url'])
            st.caption('Found on: '+row['found_on'])
            with st.form('candidate-'+str(row['id'])):
                name=st.text_input('Source name',row['name'])
                url=st.text_input('Job listing URL',row['url'])
                approve=st.form_submit_button('Approve and add source')
                dismiss=st.form_submit_button('Dismiss')
            if approve or dismiss:
                try:
                    if approve: save_sources(config().sources+[dict(name=name,url=url,pattern="",enabled=True)])
                    with db.connect() as c: c.execute('UPDATE source_suggestions SET state=? WHERE id=?',('approved' if approve else 'dismissed',row['id']))
                    st.rerun()
                except Exception as exc: st.error(str(exc))
