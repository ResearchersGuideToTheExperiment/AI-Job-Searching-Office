import pytest
from office.content_cleaner import clean_text,document_relevant
from office.advertisement import IdentityError


def test_noise_blocks_before_inference():
    with pytest.raises(IdentityError,match='navigation'):
        clean_text('For candidates\nFor employers\n'+ 'Job duties. '*40)


def test_exact_duplicate_preserves_requirements():
    paragraph='Applicants must hold a PhD. Salary is £40,000. Apply by 30 November. '+ 'Research experience required. '*3
    assert clean_text(paragraph+'\n\n'+paragraph)==paragraph.strip()


def test_documents_require_relevance():
    assert not document_relevant('Diversity','https://uni/Example-Dei-Manifesto.pdf','Policy','Lecturer')
    assert document_relevant('Person specification','https://uni/spec.pdf','Must have a PhD','Lecturer')
