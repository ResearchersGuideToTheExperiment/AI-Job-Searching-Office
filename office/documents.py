"""Requested-document planning, verified fact selection and versioned DOCX exports."""
import json
import re
import uuid
from pathlib import Path
from typing import Annotated
from pydantic import Field
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from office.models import StrictModel, Analysis
from office.ollama import OllamaClient, OllamaError
from office.evaluation import evaluation_current
from office.activity import tracked

ALIASES = {
    'cv': r'\b(cv|curriculum vitae|resume|résumé|lebenslauf)\b',
    'cover_letter': r'\b(cover(?:ing)? letter|motivation letter|letter of (?:motivation|application)|anschreiben|motivationsschreiben)\b',
    'supporting_statement': r'\b(supporting statement|personal statement)\b',
    'selection_response': r'\b(responses? to (?:the )?selection criteria|selection criteria statement|statement addressing (?:the )?selection criteria)\b',
    'research_statement': r'\b(research statement|research proposal|statement of research)\b',
}
TITLES = {'cv': 'Tailored CV', 'cover_letter': 'Cover letter', 'supporting_statement': 'Supporting statement',
          'selection_response': 'Selection criteria response', 'research_statement': 'Research statement', 'answer': 'Application answer', 'manual': 'Material to provide manually'}


def numeric_limit(text, unit):
    patterns = [rf'(?:maximum|max\.?|up to|no more than|limit(?: of)?|at most)\s*(\d[\d,]*)\s*[- ]?{unit}s?\b',
                rf'\b(\d[\d,]*)[- ]{unit}s?\s*(?:maximum|max\.?|limit)\b', rf'\b(\d[\d,]*)-{unit}\b']
    values = [int(m.replace(',', '')) for p in patterns for m in re.findall(p, text, flags=re.I)]
    return min(values) if values else None


def plan_documents(analysis):
    items = []
    for index, req in enumerate(analysis.requirements):
        if req.category not in {'document', 'question', 'application'}:
            continue
        if req.category == 'question':
            kinds = ['answer']
        else:
            kinds = [kind for kind, pattern in ALIASES.items() if re.search(pattern, req.text, re.I)]
        # Never generate certificates, transcripts, reference letters, signed declarations, etc.
        if req.category == 'document' and (not kinds or re.search(r'\b(referee|reference|certificate|transcript|passport|portfolio|diploma)', req.text, re.I)):
            kinds.append('manual')
        for kind in kinds:
            # Explicit negatives must not become requested documents.
            negative = re.search(r'\b(not required|do not (?:send|include|attach)|nicht erforderlich)\b', req.text, re.I)
            if negative and kind != 'manual':
                kind = 'manual'
            key = f'{index}-{kind}'
            if any(item['key'] == key for item in items):
                continue
            limits_text = req.text
            if kind != 'answer' and len([k for k in kinds if k != 'manual']) > 1:
                # Attribute a local numeric cap to its nearest named document.
                # The full instruction remains visible for human review of shared constraints.
                named = [(k, m.start(), m.end()) for k in kinds if k in ALIASES for m in re.finditer(ALIASES[k], req.text, re.I)]
                local_limits = []
                for m in re.finditer(r'(?:maximum|max\.?|up to|no more than|at most)?\s*\d[\d,]*[- ]+(?:words?|characters?|pages?)(?:\s*(?:maximum|limit))?', req.text, re.I):
                    nearest = min(named, key=lambda n: min(abs(m.start()-n[2]), abs(n[1]-m.end()))) if named else None
                    if nearest and nearest[0] == kind:
                        local_limits.append(m.group())
                limits_text = ' '.join(local_limits)
            question_number = re.search(r'(?:question\s+|^\s*)(\d+)', req.text, re.I) if kind == 'answer' else None
            title = TITLES[kind] + (f' {question_number.group(1)}' if question_number else '')
            items.append({'key': key, 'kind': kind, 'title': title,
                'requirement_index': index, 'source_quote': req.source_quote, 'instructions': req.text,
                'importance': req.importance, 'word_limit': numeric_limit(limits_text, 'word'),
                'character_limit': numeric_limit(limits_text, 'character'), 'page_limit': numeric_limit(limits_text, 'page'),
                'manual': kind == 'manual'})
    return items


class FactSelection(StrictModel):
    fact_ids: list[int] = Field(min_length=1, max_length=6)


class DraftPlan(StrictModel):
    paragraphs: list[FactSelection] = Field(max_length=12)
    missing_information: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(max_length=6)


DRAFT_OUTPUT_TOKENS = 1536
DRAFT_PROMPT = (
    'Select and order confirmed facts for exactly the requested document or question. '
    'Return a compact plan of paragraphs containing fact_ids only, never prose or evidence quotes. '
    'Copy the exact numeric id values from confirmed_facts, not list positions or new numbering. '
    'Omit identity/contact facts. Use each ID at most once. '
    'Each selected fact will be exported in FULL with minimal grammatical changes; it will not be summarized. '
    'Choose relevant facts that address the source instructions and job criteria, grouping related facts into paragraphs. '
    'Respect document word/character limits INCLUDING its title and the full selected fact texts. '
    'Use at most 12 paragraphs with at most 6 IDs each; fewer when sufficient. '
    'Never invent qualifications, achievements, motivations, commitments or future research plans. '
    'List unanswered requirements or missing research plans in missing_information: at most 6 short notes, '
    'each at most 160 characters. Return [] when nothing is missing. '
    'Style preferences affect ordering only; they are not facts and must not change this JSON format.'
)


def select_draft(client, data):
    """Keep model output independent of fact length; never accept a partial plan."""
    allowed_ids = {fact['id'] for fact in data['confirmed_facts'] if fact['category'] != 'identity'}
    feedback = ''
    for attempt in range(2):
        prompt = DRAFT_PROMPT
        if attempt:
            prompt += (' The previous response was incomplete or invalid. Return a shorter valid plan using '
                       'only supplied fact IDs. Keep missing-information notes brief; do not copy any source text.')
            prompt += feedback
        try:
            draft = client.structured(DraftPlan, prompt, data, max_output_tokens=DRAFT_OUTPUT_TOKENS)
            invalid_ids = {ident for paragraph in draft.paragraphs for ident in paragraph.fact_ids} - allowed_ids
            if invalid_ids:
                error = OllamaError(f'Draft selected fact IDs outside the confirmed drafting context: {sorted(invalid_ids)}; no document was exported.')
                error.kind = 'schema'
                raise error
            return draft
        except OllamaError as exc:
            if attempt or getattr(exc, 'kind', None) not in {'output_limit', 'schema'}:
                raise
            feedback = f' Valid fact IDs are {sorted(allowed_ids)}.'


def count_words(text):
    return len(re.findall(r"\S+", text))


def factual_sentence(fact):
    """Use the entire confirmed fact; never accept an LLM's expanded paraphrase."""
    text = fact['text'].strip()
    if re.match(r'^(I |My |We )', text):
        return text
    if re.match(r'^(Designed|Tested|Taught|Developed|Conducted|Managed|Led|Published|Worked|Analyzed|Analysed|Supervised|Coordinated|Presented|Completed|Investigated)\b', text):
        text = 'I ' + text[0].lower() + text[1:]
    elif fact['category'] == 'education':
        text = 'My education includes: ' + text
    elif fact['category'] == 'certificates':
        text = 'My certificates include: ' + text
    elif fact['category'] == 'languages':
        text = 'My language skills are: ' + text
    elif fact['category'] == 'skills':
        text = 'My skills include: ' + text
    elif fact['category'] == 'publications':
        text = 'My publication record includes: ' + text
    else:
        # Non-sentence facts remain an explicit record, without inferred dates or roles.
        text = 'Relevant experience: ' + text
    return text if text.endswith(('.', '!', '?')) else text + '.'


def compose_verified(draft, context, item, job_context):
    lookup = {f['id']: f for f in context}
    paragraphs, evidence, used = [], [], set()
    if item['kind'] == 'cover_letter':
        title = job_context.get('title') or '[POSITION TITLE]'
        institution = job_context.get('institution')
        paragraphs.append(f"I am applying for the {title} position" + (f" at {institution}." if institution else '.'))
    for paragraph in draft.paragraphs:
        sentences = []
        for ident in paragraph.fact_ids:
            fact = lookup.get(ident)
            if fact and fact['id'] not in used and fact['category'] != 'identity':
                sentences.append(factual_sentence(fact))
                evidence.append({'fact_id': fact['id'], 'quote': fact['text']})
                used.add(fact['id'])
        if sentences:
            paragraphs.append(' '.join(sentences))
    if not evidence:
        paragraphs.append('[ADD VERIFIED INFORMATION — no relevant confirmed evidence was selected]')
    if draft.missing_information:
        paragraphs.append('[ADD VERIFIED INFORMATION — review the missing-information list in the dashboard]')
    if item['kind'] == 'cover_letter':
        paragraphs.append('Thank you for considering my application.')
    return '\n\n'.join(paragraphs), evidence


def check_limits(item, body):
    warnings = []
    counted = item['title'] + '\n' + body
    if item['word_limit'] and count_words(counted) > item['word_limit']:
        warnings.append(f"Over word limit (including title): {count_words(counted)} / {item['word_limit']}. Edit before submission.")
    if item['character_limit'] and len(counted) > item['character_limit']:
        warnings.append(f"Over character limit (including title): {len(counted)} / {item['character_limit']}. Edit before submission.")
    if item['page_limit']:
        warnings.append(f"Verify rendered length is at most {item['page_limit']} pages in your Word editor.")
    if re.search(r'\bpdf\b', item['instructions'], re.I):
        warnings.append('Employer requests PDF. Review this editable DOCX, then export it to PDF manually.')
    if re.search(r'\b(font|spacing|margin|format|template|signed|signature)\b', item['instructions'], re.I):
        warnings.append('Verify employer-specific formatting or signing instructions against the source.')
    if item['importance'] != 'mandatory':
        warnings.append('This item is preferred or unclear; verify whether to include it.')
    return warnings


def write_docx(path, title, body):
    document = Document()
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Inches(.75)
    section.left_margin = section.right_margin = Inches(.85)
    section.page_width, section.page_height = Inches(8.27), Inches(11.69)
    for name in ['Normal', 'Title', 'Heading 1', 'Heading 2']:
        style = document.styles[name]
        style.font.name = 'Calibri'
        style.font.color.rgb = RGBColor(0, 0, 0)
    normal = document.styles['Normal']
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(7)
    normal.paragraph_format.line_spacing = 1.08
    document.styles['Title'].font.size = Pt(19)
    document.styles['Heading 1'].font.size = Pt(13)
    document.add_heading(title, 0)
    for paragraph in body.split('\n\n'):
        if paragraph.startswith('## '):
            document.add_heading(paragraph[3:], 1)
        else:
            document.add_paragraph(paragraph)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)


def save_version(db, package, item, body, evidence, warnings, origin='AI'):
    # All file and folder names are app-controlled, never paths supplied by the model.
    path = db.path.parent / 'applications' / f"job-{package['job_id']}" / f"package-{package['id']}" / f"{item['key']}-{uuid.uuid4().hex[:10]}.docx"
    write_docx(path, item['title'], body)
    db.save_draft(package['id'], item['key'], item['title'], body, evidence, warnings, path, origin)
    return path


@tracked(3,'Preparing application document')
def generate_document(db, job_id, item_key, settings):
    from office.decisions import require_approval
    require_approval(db,job_id)
    package = db.package(job_id)
    evaluation = db.evaluation(job_id)
    if not package or not evaluation_current(db, job_id, evaluation) or package['evaluation_id'] != evaluation['id']:
        raise ValueError('Profile or job evaluation changed. Evaluate again and prepare a new package plan first.')
    item = next(i for i in json.loads(package['plan']) if i['key'] == item_key)
    if item['manual']:
        raise ValueError('This material must be provided by you; no AI document will be generated.')
    facts = db.facts(True)
    evaluation_data = json.loads(evaluation['payload'])
    relevant_ids = {e['fact_id'] for r in evaluation_data['criteria'] for e in r['evidence']}
    ordered = sorted(facts, key=lambda f: (f['category'] != 'identity', f['id'] not in relevant_ids, f['id']))
    warnings = ['Draft requires your factual and formatting review before use.']
    if not any(f['category'] == 'identity' for f in facts):
        warnings.append('No confirmed identity/contact fact is available. Add and confirm your name and contact details before finalizing documents.')
    run = db.operation_start(f"generate {item['title']}", settings.model, job_id)
    try:
        if item['kind'] == 'cv':
            # Verbatim confirmed facts: selection/order is tailored, facts are never rewritten.
            sections = []
            for category in dict.fromkeys(f['category'] for f in ordered):
                sections.append('## ' + category.replace('_', ' ').title())
                sections.extend(f['text'] for f in ordered if f['category'] == category)
            body = '\n\n'.join(sections)
            evidence = [{'fact_id': f['id'], 'quote': f['text']} for f in ordered]
        else:
            if item['kind'] == 'research_statement' and not any(f['category'] in {'research', 'projects', 'publications'} for f in facts):
                raise ValueError('A research statement needs confirmed research/project evidence. Add it to My Profile first.')
            context, size, omitted = [], 0, []
            for fact in ordered:
                if fact['category'] == 'identity':
                    continue
                entry = {k: fact[k] for k in ('id','category','text')}
                cost = len(json.dumps(entry, ensure_ascii=False).encode())
                if size + cost <= 7500:
                    context.append(entry)
                    size += cost
                else:
                    omitted.append(fact['id'])
            if omitted:
                warnings.append(f'Profile facts excluded from this drafting context due to context budget: {omitted}. Review whether they should be included.')
            analysis = Analysis.model_validate_json(db.job(job_id)['analysis'])
            job_context = {k: getattr(analysis, k).value for k in ('title','institution','location')}
            job_criteria, criteria_size = [], 0
            for criterion in analysis.requirements:
                if criterion.category in {'eligibility', 'essential', 'desirable'}:
                    entry = {'category': criterion.category, 'criterion': criterion.text, 'importance': criterion.importance}
                    cost = len(json.dumps(entry, ensure_ascii=False).encode())
                    if criteria_size + cost <= 3000:
                        job_criteria.append(entry)
                        criteria_size += cost
                    else:
                        warnings.append('A job criterion was outside this document context budget; check coverage: ' + criterion.text)
            client = OllamaClient(settings)
            data = {'document': item, 'job': job_context, 'job_criteria': job_criteria, 'confirmed_facts': context, 'style_preferences': db.preferences()['style']}
            draft = select_draft(client, data)
            # No model-written personal claims or quotes: both come directly from
            # confirmed facts, after validating every selected ID above.
            body, evidence = compose_verified(draft, context, item, job_context)
            warnings.append('Fact-preserving draft: the AI selects relevant confirmed facts; exported personal claims use their full text with minimal grammatical changes. Edit transitions and add any missing details only after verifying them.')
            warnings.extend(draft.missing_information)
        warnings.extend(check_limits(item, body))
        if not body.strip():
            raise ValueError('No supported draft content was produced.')
        # Do not export drafts that are already known to violate explicit word/character caps.
        if any(w.startswith('Over ') for w in warnings):
            raise ValueError('Draft exceeds an explicit length limit; no DOCX was exported. Narrow confirmed facts or retry generation. ' + '; '.join(w for w in warnings if w.startswith('Over ')))
        if not evaluation_current(db, job_id, evaluation):
            raise ValueError('The confirmed profile or job changed during generation. Evaluate again before generating a draft.')
        require_approval(db,job_id)
        if db.evaluation(job_id)['id'] != evaluation['id']:
            raise ValueError('The evaluation changed during generation. Review the new evaluation before drafting.')
        path = save_version(db, package, item, body, evidence, warnings)
        db.operation_finish(run, 'success', str(path))
        return path
    except Exception as exc:
        db.operation_finish(run, 'failed', str(exc))
        raise


def prepare_package(db, job_id):
    from office.decisions import require_approval
    require_approval(db,job_id)
    evaluation = db.evaluation(job_id)
    if not evaluation_current(db, job_id, evaluation):
        raise ValueError('Run an up-to-date job evaluation first.')
    analysis = Analysis.model_validate_json(db.job(job_id)['analysis'])
    plan = plan_documents(analysis)
    if not plan:
        raise ValueError('No requested documents/questions identified. Verify the original advertisement and extracted requirements first.')
    package_id = db.save_package(job_id, evaluation['id'], plan)
    return package_id
