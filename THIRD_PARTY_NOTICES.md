# Third-party license and publication review

Reviewed on 23 November 2026 for the source-only GitHub release. **No remaining licensing blocker was identified for publishing this project's own code under MIT**, within the scope below. This is a technical license review, not a legal opinion or a guarantee of ownership, patent clearance, or compliance for every downstream use.

## PDF dependency changed

The previous PDF reader, PyMuPDF, offers AGPL and commercial licensing. AGPL is an open-source license, so this did not prohibit an open-source release, but it introduced stronger obligations than an unrestricted MIT-only description would suggest. See [PyMuPDF's licensing statement](https://github.com/pymupdf/PyMuPDF#licensing).

PDF text extraction now uses **pypdf (BSD-3-Clause)**. PyMuPDF, its companion packages, and their unused dependencies were removed from the freshly generated dependency snapshot. The project does not copy PyMuPDF code. PDF import tests cover text extraction, malformed files, encrypted files, blank pages, and the 100-page limit. The replacement can produce different reading order or whitespace on complex PDFs; review extracted CV facts. See [pypdf's license](https://github.com/py-pdf/pypdf/blob/main/LICENSE).

## Direct Python dependencies

The exact installed versions and all 58 direct/transitive package declarations are in [the dependency inventory](docs/DEPENDENCY_LICENSES.md) and `requirements.lock.txt`.

| Dependency | Declared license | Use |
| --- | --- | --- |
| [Streamlit](https://github.com/streamlit/streamlit/blob/develop/LICENSE) | Apache-2.0 | Local dashboard |
| [Pydantic](https://github.com/pydantic/pydantic/blob/main/LICENSE) | MIT | Data validation |
| [pypdf](https://github.com/py-pdf/pypdf/blob/main/LICENSE) | BSD-3-Clause | PDF text extraction |
| [Requests](https://github.com/psf/requests/blob/main/LICENSE) | Apache-2.0 | HTTP requests |
| [pytest](https://github.com/pytest-dev/pytest/blob/main/LICENSE) | MIT | Tests |
| [python-docx](https://github.com/python-openxml/python-docx/blob/master/LICENSE) | MIT | DOCX import/export |
| [Beautiful Soup](https://pypi.org/project/beautifulsoup4/) | MIT | HTML parsing |
| [Trafilatura](https://github.com/adbar/trafilatura/blob/master/LICENSE) | Apache-2.0 | Web content processing |
| [dateparser](https://github.com/scrapinghub/dateparser/blob/master/LICENSE) | BSD-3-Clause | Deadline parsing |
| [pandas](https://github.com/pandas-dev/pandas/blob/main/LICENSE) | BSD-3-Clause | Data tables |
| [tzdata](https://github.com/python/tzdata/blob/master/LICENSE) | Apache-2.0 package; IANA data has its own public-domain notice | Time zones |

These components retain their own licenses. Their license, attribution, disclaimer, and applicable notice terms still matter if their code or binaries are redistributed. The project's MIT license does not replace those terms.

## Transitive dependencies and future bundles

Most installed distributions declare MIT, BSD, Apache, or related permissive terms. **certifi declares MPL-2.0**, a file-level copyleft license: using it does not require unrelated application files to become MPL, but redistributing its covered files carries notice/source obligations. See [certifi's license](https://github.com/certifi/python-certifi/blob/master/LICENSE) and [Mozilla's explanation](https://www.mozilla.org/en-US/MPL/2.0/FAQ/).

The inventory also records combined or less familiar declarations such as regex's Apache-2.0 AND CNRI-Python, Pillow's MIT-CMU, and typing_extensions' PSF-2.0. These are not described as MIT-only.

The source ZIP contains no installed packages, model weights, Python runtime, native libraries, or executable bundle. A future installer, container, or standalone executable must be reviewed separately, including licenses of libraries bundled inside dependency wheels, and must carry required notices and source-access information. This metadata review is not an exhaustive binary component audit.

## Ollama and the suggested model

- [Ollama](https://github.com/ollama/ollama/blob/main/LICENSE) declares MIT for its project code and is installed separately. Its distribution may include additional components under their own licenses.
- The suggested [Qwen3 8B model](https://huggingface.co/Qwen/Qwen3-8B/blob/main/LICENSE) is Apache-2.0. Model weights are downloaded separately; the source archive does not redistribute them.
- Other GGUFs or alternative models may have different terms. This review does not cover arbitrary files users put in the model folder. The app's MIT license does not relicense models, their outputs, or user documents.

## Project files and third-party content

The public manifest was inspected for bundled dependencies, binary assets, real CVs, captured adverts, proprietary notices, and identifying job history. No separate proprietary SDK, model weights, paid template, bundled font, or third-party illustration is included. Document code names fonts but does not bundle font files.

HTML fixtures are hand-authored fictional examples. A jobs.ac.uk hostname is used to exercise a parser branch; fixture employers, identifiers, descriptions, and application links are fictional. This does not imply affiliation or endorsement.

The release does not include downloaded job adverts or personal application records. Users must separately respect website access terms and rights in retrieved content; releasing this code does not grant permission to republish website content. The retriever implements robots checks and does not bypass login/CAPTCHA restrictions.

The original project code is offered under [MIT](LICENSE). The file inspection cannot prove authorship of every historical contribution or determine whether an employer, collaborator, or other party has rights outside this folder. Any such externally known obligation still needs to be resolved by the owner before publication.

