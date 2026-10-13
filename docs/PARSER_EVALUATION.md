# Stage 3 parser selection

Local evaluation on 2026-10-13. PDFs and page renders remain in ignored `data/parser-evaluation/`; no paper content is committed. `scripts/evaluate_parsers.py` reproduces the text/anchor observations on supplied local PDFs.

## Candidates and licensing

| Candidate | License / execution | Assessment |
|---|---|---|
| pypdf 6.20.1 | BSD-3-Clause; local Python; no ML weights | Selected for page text, PDF Info and embedded raster decoding |
| pdfplumber 0.11.10 | MIT; pdfminer.six; local Python and PDFium dependencies | Selected only for image placement; text-flow extraction was also evaluated |
| Docling native parser 7.22.3 | MIT; C++ decoding with Docling core types | Executed in a separate ignored environment; no OCR/layout ML models were run |
| Full Docling pipeline | MIT package; model licenses must be reviewed separately; PyTorch and downloaded artifacts for model stages | Documentation/resource assessment only; default layout/OCR pipeline was not benchmarked or integrated |
| PyMuPDF | AGPL/commercial licensing | Not selected; no runtime quality claim is made |

The native Docling evaluation is not a benchmark of full Docling. Its text-line cells are exported in native order; image reconstruction and semantic layout are not compared. The selected adapter remains replaceable.

Sources: [pypdf project](https://github.com/py-pdf/pypdf), [pypdf extraction limitations](https://pypdf.readthedocs.io/en/stable/user/extract-text.html), [pdfplumber](https://github.com/jsvine/pdfplumber), [Docling native parser](https://github.com/docling-project/docling-parse), [Docling installation](https://docling-project.github.io/docling/getting_started/installation/), [Docling model artifacts](https://docling-project.github.io/docling/usage/advanced_options/), [PyMuPDF licensing](https://pymupdf.readthedocs.io/en/latest/about.html).

## Representative sources

| Local label | Source / inspected PDF version | Pages | SHA-256 of evaluated bytes |
|---|---|---:|---|
| Attention | [Attention Is All You Need](https://arxiv.org/abs/1706.03762), v7 | 15 | bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697 |
| RAG | [Retrieval-Augmented Generation](https://arxiv.org/abs/2005.11401), v4 | 19 | 23e3249e9a1e75418d82efecab0ea8c4d033b89c93742f63208d47ce01f21233 |
| Mamba | [Mamba](https://arxiv.org/abs/2312.00752), v2 | 36 | adf70ed1803c85b1899dec3e21f3af0b124411439e8654b840ea65f7b9f52b2e |

First pages were rendered with Poppler and inspected against extracted titles/headings. These are digitally generated papers with varied layout, formulas, tables and raster/vector figures; they do not represent every research field or language. Synthetic reportlab fixtures separately cover exact page references, sections, captions, raster images, image-only documents, encryption and size limits.

## Recorded observations

| Source | pypdf characters / raster object references | pdfplumber characters / image objects | Docling native text characters |
|---|---|---|---:|
| Attention | 39,585 / 3 | 36,166 / 3 | 39,595 |
| RAG | 69,044 / 2 | 62,533 / 2 | 69,177 |
| Mamba | 156,637 / 0 | 120,667 / 0 | 135,339 |

All three candidates recovered non-empty text on all pages. The pypdf sample runs found both configured heading/title anchors on each paper; pdfplumber text-flow missed the Attention positional-encoding anchor. Text counts and a few matching anchors do **not** establish semantic accuracy, reading order, formula fidelity or figure completeness. Zero raster objects does not mean a paper has no figures: Mamba contains vector artwork.

Individual local elapsed times included interpreter imports and ranged from 0.671–1.611 seconds for pypdf and 1.354–2.809 seconds for pdfplumber. These are single observations with cold imports and uncontrolled host load, not repeatable performance rankings. Full ML Docling runtime/RAM and OCR quality were not measured.

## Selected initial behavior

The complete selected adapter was also executed in the Linux test container through its actual bounded child-process runner (60 seconds, 1024 MiB), rather than only calling text extraction directly. All three runs produced `ready` within the adapter's supported scope, with non-empty text on every page and the explicit global warnings below. Attention produced 15 pages, 7 candidate sections and 3 decoded raster images; RAG produced 19/9/2; Mamba produced 36/7/0. Both configured anchors were found on each source. Individual elapsed observations were 4.603, 1.847 and 3.357 seconds respectively; they remain uncontrolled single runs and do not measure semantic accuracy. The original bytes matched the hashes above.

Reproduce against a supplied local PDF in an environment with the locked backend dependencies:

```powershell
python scripts/evaluate_parsers.py --parser selected --pdf path/to/paper.pdf --output data/parser-evaluation/selected.json --anchor "Expected heading"
```

The record contains counts, warnings and anchor matches, not extracted paper content. Candidate-native runs use `--parser pypdf`, `pdfplumber` or `docling-native`; the latter requires its separate optional environment.

- Preserve normalized page text with one-based page IDs and exact section offsets; headings are pattern-based candidates, not scientific interpretation.
- Keep PDF Info and detected DOI strings explicitly unverified; do not overwrite user titles or invent missing authors, dates or identifiers.
- Decode embedded raster images to PNG, keeping page references and bounding boxes when the source object can be mapped. Original PDF remains unchanged. Vector figure/table reconstruction is unavailable.
- Associate a caption only as a candidate when a page has exactly one raster object and one matching figure-caption line; record that heuristic and source offsets. Otherwise leave the caption null.
- Image-only/failed pages and omitted images produce explicit partial results. OCR is unavailable in this adapter. No document text, URLs or embedded instructions are executed or sent externally.
- Execute parsing in a bounded child process. Persist its parser/dependency versions and frozen limits on each immutable document version. This is process/resource isolation, not an OS security sandbox.

PyPI index access timed out locally. Tsinghua's HTTPS mirror was used to resolve metadata; lockfile package URLs were normalized to official PyPI/files.pythonhosted.org locations without changing hashes, and installation from the resulting frozen lock succeeded. No mirror or proxy was configured globally.
