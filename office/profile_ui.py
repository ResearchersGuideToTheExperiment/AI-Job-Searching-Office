from office.control import Cancelled
import streamlit as st
import hashlib
import json
from office.career import CATEGORIES, upload_career, extract_career
from office.local_files import sync_local_files


def profile_page(db, settings):
    st.subheader('My Profile')
    st.info('Review your CV facts in the table below. Rows are treated as correct by default in the review, but they only become verified when you click Confirm all reviewed information. Originals are preserved unchanged.')
    st.caption('PDF/DOCX files in the project PUT_YOURCV_HERE folder are imported automatically. Open Original CV and supporting materials below and click Extract / retry to process them.')
    if st.button('Rescan CV folder / restore removed folder CVs'):
        notes = sync_local_files(db, restore_cv=True)
        st.session_state['profile_review_result'] = ' '.join(notes) or 'CV folder checked. All supported files are already registered.'
        st.rerun()
    operations = db.operations()
    if operations and operations[0]['state'] in {'needs_review', 'failed'}:
        st.warning('The latest extraction needs review. Valid facts are retained; check omissions and source-quote replacements below.')
        st.text(operations[0]['detail'])
    with st.form('profile_upload'):
        kind = st.selectbox('Material type', ['master_cv', 'cover_letter', 'research_statement', 'publication_list', 'certificate', 'other'])
        upload = st.file_uploader('Master CV or supporting material', type=['pdf', 'docx', 'txt'])
        save = st.form_submit_button('Save original and extract facts')
    if save:
        if upload is None:
            st.error('Choose a document first.')
        else:
            try:
                document_id = upload_career(db, upload.name, upload.getvalue(), kind)
                st.success('Original saved.')
                with st.spinner('Extracting career facts locally…'):
                    message = st.empty()
                    extract_career(db, document_id, settings, message.text)
                st.success('Extraction finished. Review the facts and the processing report below.')
                st.text(db.operations()[0]['detail'])
            except (Exception,Cancelled) as exc:
                st.error(str(exc))
    with st.expander('Original CV and supporting materials'):
        for row in db.profile_documents():
            doc = db.profile_document(row['id'])
            st.text(f"{row['name']} · {row['kind']} · {row['created_at']} UTC")
            st.download_button('Download preserved original', doc['content'], file_name=doc['name'], key=f"original-profile-{row['id']}")
            with st.form(f"remove-profile-{row['id']}"):
                remove_ok = st.checkbox(f"Remove {row['name']} and its extracted facts from my profile")
                st.caption('Computer files and application history are kept. Use Rescan CV folder above to restore a removed folder CV.')
                if st.form_submit_button('Remove document'):
                    if remove_ok:
                        db.remove_profile_document(row['id'])
                        st.session_state['profile_review_result'] = f"Removed {row['name']} and its extracted facts."
                        st.rerun()
                    else:
                        st.warning('Tick the confirmation for this document, then click Remove document.')
            st.text(doc['text'])
            if st.button('Extract / retry without overwriting reviewed facts', key=f"retry-profile-{row['id']}"):
                try:
                    with st.spinner('Extracting…'):
                        extract_career(db, row['id'], settings)
                    st.rerun()
                except (Exception,Cancelled) as exc:
                    st.error(str(exc))
    st.subheader('Career information')
    st.caption('Identical facts from multiple CV versions are shown once. Your review applies to all identical copies; original documents and source quotes are retained.')
    facts = db.facts()
    st.caption(f"{sum(f['confirmed'] for f in facts)} confirmed / {len(facts)} total facts")
    if 'profile_review_result' in st.session_state:
        st.success(st.session_state.pop('profile_review_result'))
    if facts:
        st.write('Tick **Incorrect** for anything wrong. Edit its **Fact** or **Category** directly in the table, then confirm everything once below. A flagged row with no correction stays excluded; a corrected row is confirmed. Unticked rows are confirmed as shown.')
        names = {d['id']: d['name'] for d in db.profile_documents()}
        rows = [{'Incorrect': bool(f['reviewed_at'] and not f['confirmed']), 'Category': f['category'],
                 'Fact': f['text'], 'Source quote': f['source_quote'] or '',
                 'Document': names.get(f['document_id'], 'Manual entry'), 'ID': f['id']} for f in facts]
        revision = hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()[:16]
        with st.form('bulk-profile-review'):
            edited = st.data_editor(rows, hide_index=True, num_rows='fixed', width='stretch',
                height=min(850, 80 + 100 * len(rows)), row_height=100,
                disabled=['Source quote', 'Document', 'ID'], key=f'career-review-{revision}',
                column_config={
                    'Incorrect': st.column_config.CheckboxColumn('Incorrect', help='Tick to flag a wrong fact. Correct its text/category, or leave it flagged and unchanged to exclude it.'),
                    'Category': st.column_config.SelectboxColumn(options=list(CATEGORIES), required=True),
                    'Fact': st.column_config.TextColumn(width='large', required=True, max_chars=2500),
                    'Source quote': st.column_config.TextColumn(width='large'),
                    'Document': st.column_config.TextColumn(width='medium'), 'ID': None})
            if st.form_submit_button('Confirm all reviewed information', type='primary'):
                try:
                    confirmed, excluded = db.confirm_fact_review(edited, facts)
                    st.session_state['profile_review_result'] = f'Saved: {confirmed} confirmed facts; {excluded} flagged facts excluded.'
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    else:
        st.info('Import and extract a CV to populate the review table.')
    with st.expander('Add a missing fact manually'):
        with st.form('new-fact', clear_on_submit=True):
            category = st.selectbox('Category', CATEGORIES)
            value = st.text_area('Fact', max_chars=2500)
            confirmed = st.checkbox('I confirm this new fact is accurate')
            if st.form_submit_button('Add fact'):
                try:
                    db.save_fact(None, category, value, confirmed)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    prefs = db.preferences()
    with st.form('preferences'):
        st.subheader('Writing style and job preferences')
        st.caption('Linked files: PUT_YOUR_AI_MODEL_HERE/AI_instructions/writing_style.md and job_preferences.md. Changed files refresh these fields on the next dashboard rerun. Saving here does not modify your Markdown files. Full text is stored; model context limits still apply during drafting, with explicit errors rather than truncation.')
        style = st.text_area('Writing style', prefs['style'], height=240)
        preferences = st.text_area('Application preferences (locations, roles, constraints)', prefs['preferences'], height=240)
        if st.form_submit_button('Save preferences'):
            db.save_preferences(style, preferences)
            st.success('Preferences saved. Preferences never count as qualifications.')
    with st.expander('Profile processing history'):
        st.json(db.operations())
