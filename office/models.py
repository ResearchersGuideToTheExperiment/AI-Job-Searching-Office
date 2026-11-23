from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
import re
import unicodedata
import html


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fact(StrictModel):
    value: str | None = Field(description="Exact substring from the ad, or null if absent. Never infer.")
    source_quote: str | None = Field(description="Verbatim supporting quote from the advertisement, or null.")


class Requirement(StrictModel):
    category: Literal["eligibility", "essential", "desirable", "document", "question", "application"]
    text: str = Field(min_length=1, description="Exact requirement text copied from the advertisement.")
    importance: Literal["mandatory", "preferred", "unclear"]
    source_quote: str = Field(min_length=1, description="Verbatim supporting passage including mandatory/preference wording.")


class Analysis(StrictModel):
    title: Fact
    institution: Fact
    location: Fact
    job_type: Fact
    salary: Fact
    deadline: Fact
    submission_method: Fact
    application_url: Fact
    application_email: Fact
    requirements: list[Requirement]


class CriteriaExtraction(StrictModel):
    requirements: list[Requirement] = Field(description='Every eligibility, essential and desirable criterion. Not application documents or submission procedures.')


FACT_FIELDS = tuple(name for name in Analysis.model_fields if name != "requirements")
STATUSES = ("New", "Reviewing", "Preparing", "Ready for manual submission", "Submitted manually", "Interview", "Offer", "Rejected", "Withdrawn")


def normalize(text: str) -> str:
    return evidence_map(text)[0]


def evidence_map(text):
    """Formatting-only normalization with a map back to the untouched evidence."""
    result,positions=[],[]
    translations=str.maketrans({'\u2018':"'",'\u2019':"'",'\u201c':'"','\u201d':'"','\u2010':'-','\u2011':'-','\u2013':'-','\u2014':'-'})
    for match in re.finditer(r'&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);|.',text,re.S):
        value=unicodedata.normalize('NFKC',html.unescape(match[0])).translate(translations).casefold()
        for char in value:
            if char in '\u00ad\u200b\ufeff':
                continue
            if char.isspace():
                char=' '
                if not result or result[-1]==' ':
                    continue
            result.append(char);positions.append((match.start(),match.end()))
    return ''.join(result).rstrip(),positions


def evidence_span(text,quote):
    normalized,positions=evidence_map(text)
    needle=normalize(quote)
    if not needle:
        return None
    start=0
    while (index:=normalized.find(needle,start))>=0:
        end=index+len(needle)
        if not (index and needle[0].isalnum() and normalized[index-1].isalnum()) and not (end<len(normalized) and needle[-1].isalnum() and normalized[end].isalnum()):
            return positions[index][0],positions[end-1][1]
        start=index+1
    return None


def verbatim(text,quote):
    span=evidence_span(text,quote)
    return text[span[0]:span[1]] if span else None


def equivalent_date(value,quote):
    from datetime import datetime
    def parsed(text):
        text=re.sub(r'(\d)(st|nd|rd|th)\b',r'\1',text,flags=re.I).strip()
        for fmt in ('%Y-%m-%d','%d %B %Y','%d %b %Y','%B %d, %Y'):
            try:
                return datetime.strptime(text,fmt).date()
            except ValueError:
                pass
        return None
    target=parsed(value)
    if target:
        for match in re.finditer(r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},\s*\d{4})\b',quote):
            if parsed(match[0])==target:
                return match[0]
    return None


def ground_analysis(analysis: Analysis, original: str) -> tuple[Analysis, list[str]]:
    """Fail closed on unsupported text. Quote presence does not prove semantic correctness."""
    result = analysis.model_copy(deep=True)
    source = normalize(original)
    warnings = []
    for name in FACT_FIELDS:
        fact = getattr(result, name)
        if name=='deadline' and fact.value and fact.source_quote:
            quote=verbatim(original,fact.source_quote)
            equivalent=equivalent_date(fact.value,quote) if quote else None
            if equivalent:
                fact.value=equivalent
        if fact.value is None or normalize(fact.value) in {'unknown','not specified','not stated','n/a','missing'}:
            fact.value=None
            fact.source_quote = None
        elif (not fact.value.strip() or not fact.source_quote or
              not verbatim(original,fact.source_quote) or
              not verbatim(verbatim(original,fact.source_quote),fact.value) or
              (name=='application_url' and not re.fullmatch(r'https?://\S+',fact.value)) or
              (name=='application_email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',fact.value))):
            setattr(result, name, Fact(value=None, source_quote=None))
            warnings.append(f"Unsupported {name} removed; verify the original advertisement.")
        else:
            fact.source_quote=verbatim(original,fact.source_quote)
            fact.value=verbatim(fact.source_quote,fact.value)
    grounded = []
    for req in result.requirements:
        quote=verbatim(original,req.source_quote)
        text=verbatim(quote,req.text) if quote else None
        if text:
            req.source_quote,req.text=quote,text
            grounded.append(req)
        else:
            warnings.append(f"Unsupported requirement removed: {req.category}. Review the original.")
    result.requirements = grounded
    return result, list(dict.fromkeys(warnings))
