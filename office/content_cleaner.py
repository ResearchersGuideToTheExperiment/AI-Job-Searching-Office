"""Deterministic text checks; never summarize or invent evidence."""
import re
from office.advertisement import IdentityError


def clean_text(text):
    text = text.replace('\r\n','\n').replace('\r','\n')
    if len(text.strip()) < 120:
        raise IdentityError('Too little advertisement text; supply the complete vacancy.')
    markers = ['For candidates', 'For employers', 'For members', 'Cookie settings', 'Accept all cookies']
    if sum(marker in text for marker in markers) >= 2:
        raise IdentityError('Saved text contains website navigation. Open Extras → Cleaning preview and use the isolated source before analysis.')
    # Only remove whole identical paragraphs, preserving lines and quoted wording.
    paragraphs = re.split(r'\n\s*\n', text.strip())
    seen = set(); result = []
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if paragraph in seen and len(paragraph) > 100:
            continue
        seen.add(paragraph); result.append(paragraph)
    return '\n\n'.join(result)


def document_relevant(label, url, text, title):
    context = (label+' '+url).lower()
    if re.search(r'manifesto|manifeso|privacy|cookie|annual.report|code.of.conduct|diversity.policy', context):
        return False
    return bool((title and title.casefold() in text.casefold()) or
                re.search(r'job.description|person.specification|selection.criteria|application.form|eligibility', context))
