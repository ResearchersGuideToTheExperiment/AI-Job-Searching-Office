from io import BytesIO
from docx import Document
from office.db import Database
from office.career import CareerExtraction, CareerFact, extract_career, upload_career, profile_fingerprint
from office.config import Settings
from office.ollama import OllamaClient
from office.chunks import split_text


def synthetic_cv():
    doc = Document()
    doc.add_heading('Alex Example', 0)
    doc.add_paragraph('PhD in Psychology, Example University, 2022.')
    doc.add_paragraph('Designed virtual reality experiments on visual perception and tested 40 participants.')
    doc.add_paragraph('Taught research methodology to undergraduate students from 2022 to 2024.')
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def test_profile_review_and_original_preservation(tmp_path, monkeypatch):
    db = Database(tmp_path / 'office.db')
    content = synthetic_cv()
    doc_id = upload_career(db, 'master.docx', content, 'master_cv')
    text = 'PhD in Psychology, Example University, 2022.'
    monkeypatch.setattr(OllamaClient, 'structured', lambda *args: CareerExtraction(facts=[CareerFact(category='education', text=text, source_quote=text)]))
    extract_career(db, doc_id, Settings())
    assert not db.facts(True)
    fact = db.facts()[0]
    db.save_fact(fact['id'], 'education', text, True)
    digest = profile_fingerprint(db.facts(True))
    extract_career(db, doc_id, Settings())
    assert len(db.facts()) == 1
    assert db.facts(True)[0]['text'] == text
    assert db.profile_document(doc_id)['content'] == content
    db.save_fact(fact['id'], 'education', text + ' Corrected.', True)
    assert profile_fingerprint(db.facts(True)) != digest
    db.save_preferences('Concise', 'Berlin')
    assert Database(db.path).preferences()['preferences'] == 'Berlin'


def test_chunks_preserve_unicode_and_boundaries():
    text = ('A long requirement ü字\n' * 800) + 'Final required criterion.'
    chunks = split_text(text)
    assert all(len(c.encode('utf-8')) <= 5500 for c in chunks)
    assert chunks[-1].endswith('Final required criterion.')
    # Every character position is covered, including the overlap.
    cursor = 0
    for chunk in chunks:
        pos = text.find(chunk, max(0, cursor - 5500))
        assert pos >= 0
    assert len(chunks) > 1
