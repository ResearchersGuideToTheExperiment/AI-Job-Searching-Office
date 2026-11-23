from pathlib import Path
from io import BytesIO
from zipfile import ZipFile, BadZipFile
from pypdf import PdfReader

MAX_BYTES = 10 * 1024 * 1024
# Conservative limit for the existing 8192-token Modelfile, schema and output combined.
MAX_AD_BYTES = 7000


def read_upload(name: str, content: bytes) -> str:
    if len(content) > MAX_BYTES:
        raise ValueError("Upload exceeds 10 MB.")
    suffix = Path(name).suffix.lower()
    if suffix == ".txt":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Save the TXT file as UTF-8 and upload it again.") from exc
    elif suffix == '.docx':
        from docx import Document
        try:
            with ZipFile(BytesIO(content)) as archive:
                if sum(x.file_size for x in archive.infolist()) > 50 * 1024 * 1024:
                    raise ValueError('DOCX expands beyond 50 MB.')
            doc = Document(BytesIO(content))
            pieces = []
            for block in doc.iter_inner_content():
                if hasattr(block, 'text'):
                    pieces.append(block.text)
                else:
                    pieces.extend(' | '.join(c.text for c in row.cells) for row in block.rows)
            for section in doc.sections:
                pieces.extend(p.text for p in section.header.paragraphs)
                pieces.extend(p.text for p in section.footer.paragraphs)
            text = '\n'.join(pieces)
        except (BadZipFile, KeyError) as exc:
            raise ValueError('Invalid DOCX file.') from exc
    elif suffix == ".pdf":
        try:
            doc = PdfReader(BytesIO(content))
            if doc.is_encrypted:
                raise ValueError("Password-protected PDFs are not supported.")
            if len(doc.pages) > 100:
                raise ValueError("PDF exceeds 100 pages.")
            text = "\n\n".join(page.extract_text() or '' for page in doc.pages)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Unable to read this PDF. Try a text PDF or paste the ad.") from exc
    else:
        raise ValueError("Only PDF, DOCX and TXT documents are supported.")
    if not text.strip():
        raise ValueError("No readable text found. Scanned PDFs need external OCR; paste the text instead.")
    return text


def check_analysis_length(text: str):
    if not text.strip():
        raise ValueError("The advertisement is empty.")
    if len(text.encode("utf-8")) > MAX_AD_BYTES:
        raise ValueError("An individual AI section exceeds the 7,000-byte safety limit. The job-analysis service must split the original into smaller sections. No text was silently truncated.")
