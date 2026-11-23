from pathlib import Path
import pytest
from pydantic import ValidationError
from docx import Document
from office.models import Analysis, Fact, Requirement, FACT_FIELDS
from office.documents import plan_documents, numeric_limit, write_docx, check_limits


def test_only_requested_documents_and_limits():
    analysis = Analysis(**{k: Fact(value=None, source_quote=None) for k in FACT_FIELDS}, requirements=[
        Requirement(category='document', text='Upload a CV and a 500-word motivation letter.', source_quote='Upload a CV and a 500-word motivation letter.', importance='mandatory'),
        Requirement(category='document', text='Provide two referee contacts; reference letters are not required.', source_quote='Provide two referee contacts; reference letters are not required.', importance='mandatory'),
        Requirement(category='question', text='Explain research methods (maximum 250 words).', source_quote='Explain research methods (maximum 250 words).', importance='mandatory')])
    plan = plan_documents(analysis)
    assert {p['kind'] for p in plan} == {'cv','cover_letter','manual','answer'}
    assert next(p for p in plan if p['kind'] == 'answer')['word_limit'] == 250
    assert numeric_limit('no more than 1,000 words', 'word') == 1000
    assert any('Over word limit' in w for w in check_limits(plan[-1], 'word ' * 251))


def test_docx_roundtrip(tmp_path):
    path = tmp_path / 'draft.docx'
    write_docx(path, 'Cover letter', 'Dear Selection Committee,\n\nI tested 40 participants.')
    doc = Document(path)
    assert 'I tested 40 participants.' in '\n'.join(p.text for p in doc.paragraphs)
    assert doc.styles['Normal'].font.size.pt == 11


def test_model_embellishment_cannot_reach_exported_claims():
    from office.documents import compose_verified, DraftPlan, FactSelection
    fact = {'id': 1, 'category': 'research', 'text': 'Tested 40 participants.'}
    with pytest.raises(ValidationError):
        FactSelection(fact_ids=[1], text='I published 50 papers and led a large laboratory.')
    draft = DraftPlan(paragraphs=[FactSelection(fact_ids=[1, 1])], missing_information=[])
    body, evidence = compose_verified(draft, [fact], {'kind': 'answer'}, {})
    assert '50 papers' not in body and 'laboratory' not in body
    assert body == 'I tested 40 participants.'
    assert evidence[0]['quote'] == fact['text']
    assert len(evidence) == 1
