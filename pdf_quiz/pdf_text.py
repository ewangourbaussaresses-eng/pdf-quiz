"""Extraction de texte depuis un PDF, sans dépendance externe.

Gère les PDF « texte » (compressés FlateDecode ou non) et les PDF dont le texte est
déjà en clair. Les PDF scannés (images seules) ne sont pas lisibles ici : ils
nécessitent un OCR (Tesseract) — voir la section « Limites » du README.
"""
from __future__ import annotations

import re
import zlib
from pathlib import Path


class PDFError(RuntimeError):
    pass


def _decode_streams(raw: bytes) -> list[str]:
    """Décompresse les flux FlateDecode et renvoie leur contenu texte."""
    chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n", raw):
        start = match.end()
        end = raw.find(b"endstream", start)
        if end == -1:
            continue
        data = raw[start:end].rstrip(b"\r\n")
        try:
            chunks.append(zlib.decompress(data).decode("latin-1"))
        except zlib.error:
            # flux non compressé ou compressé différemment : on tente en clair
            try:
                chunks.append(data.decode("latin-1"))
            except UnicodeDecodeError:
                continue
    if not chunks:
        chunks.append(raw.decode("latin-1", errors="replace"))
    return chunks


def _unescape(text: str) -> str:
    replacements = {r"\n": "\n", r"\r": "\r", r"\t": "\t", r"\(": "(", r"\)": ")",
                    r"\\": "\\"}
    for source, target in replacements.items():
        text = text.replace(source, target)
    # séquences octales \ddd
    return re.sub(r"\\([0-7]{1,3})", lambda m: chr(int(m.group(1), 8)), text)


def _text_from_content(content: str) -> str:
    """Extrait le texte affiché par les opérateurs Tj / TJ / ' / \"."""
    out: list[str] = []
    for match in re.finditer(r"\((?:\\.|[^\\()])*\)\s*Tj|\[(.*?)\]\s*TJ|"
                             r"T\*|Td|TD|ET", content, re.DOTALL):
        token = match.group(0)
        if token.endswith("Tj"):
            inner = token[: token.rfind(")")]
            out.append(_unescape(inner[inner.find("(") + 1:]))
        elif token.endswith("TJ") and match.group(1):
            parts = re.findall(r"\((?:\\.|[^\\()])*\)", match.group(1))
            out.append("".join(_unescape(p[1:-1]) for p in parts))
        else:
            out.append("\n")
    text = "".join(out)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text(path: str | Path) -> str:
    """Texte brut d'un PDF. Lève PDFError si rien n'est exploitable."""
    path = Path(path)
    if not path.exists():
        raise PDFError(f"fichier introuvable : {path}")
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF"):
        raise PDFError("ce fichier n'est pas un PDF")

    pieces = [_text_from_content(chunk) for chunk in _decode_streams(raw)]
    text = "\n".join(p for p in pieces if p)
    if len(text.strip()) < 20:
        raise PDFError("aucun texte extractible (PDF probablement scanné : OCR requis)")
    return text


def is_scanned(path: str | Path) -> bool:
    try:
        extract_text(path)
        return False
    except PDFError as exc:
        return "scanné" in str(exc)


def pages_estimate(text: str) -> int:
    return max(1, text.count("\f") + 1)


def chunk_text(text: str, size: int = 2000, overlap: int = 200) -> list[str]:
    """Découpe un texte en morceaux pour l'envoi au modèle."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind(". ", start, end)
            if cut > start + size // 2:
                end = cut + 1
        chunks.append(text[start:end].strip())
        start = max(end - overlap, start + 1)
    return chunks
