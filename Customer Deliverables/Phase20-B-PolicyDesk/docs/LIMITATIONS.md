# PolicyDesk Knowledge Assistant — Documented Limitations

This document explicitly defines the bounded operational scope, assumptions, and known limitations of the initial PolicyDesk release.

---

## 1. Document Format & Parsing Boundaries

- **Scanned PDFs & OCR**: The current release extracts digital text layers from vector PDFs using standard PDF parsing libraries. Scanned image-only PDFs (where text is embedded as bitmap images) require an optical character recognition (OCR) engine (such as Tesseract), which is not part of the initial lightweight release.
- **Office Formats**: Word (`.docx`), Excel (`.xlsx`), and PowerPoint (`.pptx`) documents are not currently ingested directly. They should be exported to `.pdf` or Markdown prior to upload.
- **Embedded Images**: Figures and diagram flowcharts inside PDFs are not visually interpreted.

---

## 2. Model & Generation Limits

- **Hallucination Mitigation**: While the system uses retrieval-grounded prompting and conservative abstention heuristics, no generative AI system guarantees zero hallucinations. All answers must be cross-referenced against the accompanying interactive citations.
- **Complex Tabular Reasoning**: Highly complex multi-dimensional tables with merged cells in PDFs are converted to linear text streams; simple rate cards are supported, but advanced financial spreadsheets should be referenced directly.
- **Single Tenant**: This product is deployed as an isolated single-tenant application for PolicyDesk. Multi-tenant multi-organization segmentation is out of scope for this benchmark release.
