"""Phase 18-D — document classification and safe parsing."""

from __future__ import annotations

from pathlib import Path

from autoforge_knowledge_platform.rag18.errors import CorruptSourceError

DOCUMENT_TYPE_BY_SUFFIX: dict[str, tuple[str, str]] = {
    ".py": ("python_source", "python"),
    ".ts": ("typescript_source", "typescript"),
    ".tsx": ("typescript_source", "typescript"),
    ".js": ("javascript_source", "javascript"),
    ".jsx": ("javascript_source", "javascript"),
    ".mjs": ("javascript_source", "javascript"),
    ".cjs": ("javascript_source", "javascript"),
    ".go": ("go_source", "go"),
    ".rs": ("rust_source", "rust"),
    ".java": ("java_source", "java"),
    ".rb": ("ruby_source", "ruby"),
    ".php": ("php_source", "php"),
    ".c": ("c_source", "c"),
    ".h": ("c_header_source", "c"),
    ".cpp": ("cpp_source", "cpp"),
    ".hpp": ("cpp_source", "cpp"),
    ".cs": ("csharp_source", "csharp"),
    ".swift": ("swift_source", "swift"),
    ".kt": ("kotlin_source", "kotlin"),
    ".kts": ("kotlin_source", "kotlin"),
    ".scala": ("scala_source", "scala"),
    ".ex": ("elixir_source", "elixir"),
    ".exs": ("elixir_source", "elixir"),
    ".sh": ("shell_script", "shell"),
    ".sql": ("sql_source", "sql"),
    ".md": ("markdown", "markdown"),
    ".markdown": ("markdown", "markdown"),
    ".mdx": ("markdown", "markdown"),
    ".txt": ("plain_text", "text"),
    ".pdf": ("pdf_document", "pdf"),
    ".json": ("json_document", "json"),
    ".yaml": ("yaml_document", "yaml"),
    ".yml": ("yaml_document", "yaml"),
    ".rst": ("restructured_text", "rst"),
    ".adoc": ("asciidoc", "asciidoc"),
    ".text": ("plain_text", "text"),
}


def classify(path: str | Path) -> tuple[str, str]:
    """Return ``(document_type, language)`` for an allowed source file."""
    suffix = Path(path).suffix.lower()
    return DOCUMENT_TYPE_BY_SUFFIX.get(suffix, ("plain_text", "text"))


def read_text(path: str | Path) -> tuple[str, str]:
    """Read a source file as text with a strict-then-lenient encoding policy.

    Supports text, source code, structured documents, and PDF documents.
    Returns ``(content, encoding)``. Raises ``CorruptSourceError`` only when
    the file cannot be decoded or parsed at all.
    """
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".pdf":
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(str(p))
            pages_text = []
            for i, page in enumerate(reader.pages):
                extracted = page.extract_text()
                if extracted and extracted.strip():
                    pages_text.append(f"--- [Page {i + 1}] ---\n{extracted.strip()}")
            if not pages_text:
                return f"[Empty or non-extractable PDF: {p.name}]", "pdf"
            return "\n\n".join(pages_text), "pdf"
        except Exception as exc:
            raise CorruptSourceError(f"Failed to parse PDF document {path}: {exc}") from exc

    raw = p.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise CorruptSourceError(f"Source not decodable as utf-8/latin-1: {path}")