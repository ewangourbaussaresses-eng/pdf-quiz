"""Tests pdf-quiz — PDF de test généré à la volée, aucun accès réseau."""
from __future__ import annotations

import json
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pdf_quiz import llm  # noqa: E402
from pdf_quiz.cli import main  # noqa: E402
from pdf_quiz.generate import (flashcards_locally, generate, keywords,  # noqa: E402
                               quiz_locally, sentences, to_tsv)
from pdf_quiz.pdf_text import PDFError, chunk_text, extract_text  # noqa: E402
from pdf_quiz.web import INDEX_HTML, _parse_multipart  # noqa: E402

LINES = [
    "Le chiffrement symetrique utilise une seule cle pour chiffrer et dechiffrer.",
    "AES est l'algorithme symetrique le plus repandu avec des cles de 256 bits.",
    "Le chiffrement asymetrique repose sur une paire de cles publique et privee.",
    "RSA est un algorithme asymetrique base sur la factorisation des grands nombres.",
    "Une fonction de hachage comme SHA-256 produit une empreinte irreversible.",
    "Un certificat X.509 lie une cle publique a une identite verifiee.",
    "TLS negocie une cle de session symetrique apres un echange asymetrique.",
    "La signature numerique garantit l'integrite et l'authenticite d'un document.",
]


def build_pdf(lines: list[str]) -> bytes:
    content_parts = ["BT", "/F1 12 Tf", "72 760 Td", "14 TL"]
    for line in lines:
        escaped = line.replace("(", "\\(").replace(")", "\\)")
        content_parts.append(f"({escaped}) Tj T*")
    content_parts.append("ET")
    compressed = zlib.compress("\n".join(content_parts).encode("latin-1"))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(compressed)).encode() +
        b" /Filter /FlateDecode >>\nstream\n" + compressed + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER", "OLLAMA_MODEL"):
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture()
def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "cours.pdf"
    path.write_bytes(build_pdf(LINES))
    return path


# --------------------------------------------------------------------------- #
# Lecture PDF
# --------------------------------------------------------------------------- #
def test_extract_text_lit_le_pdf(pdf: Path):
    text = extract_text(pdf)
    assert "chiffrement symetrique" in text
    assert "SHA-256" in text


def test_extract_refuse_non_pdf(tmp_path: Path):
    bad = tmp_path / "x.pdf"
    bad.write_text("pas un pdf", encoding="utf-8")
    with pytest.raises(PDFError):
        extract_text(bad)


def test_extract_fichier_absent(tmp_path: Path):
    with pytest.raises(PDFError):
        extract_text(tmp_path / "absent.pdf")


def test_extract_pdf_sans_texte(tmp_path: Path):
    empty = tmp_path / "vide.pdf"
    empty.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(PDFError):
        extract_text(empty)


def test_chunk_text_respecte_la_taille():
    text = ". ".join(["phrase de test assez longue"] * 400)
    chunks = chunk_text(text, size=500)
    assert len(chunks) > 1
    assert all(len(c) <= 520 for c in chunks)


def test_chunk_text_court():
    assert chunk_text("bonjour") == ["bonjour"]
    assert chunk_text("") == []


# --------------------------------------------------------------------------- #
# Génération locale
# --------------------------------------------------------------------------- #
def test_sentences_decoupe():
    text = ("Une phrase assez longue pour passer le filtre de découpe. "
            "Une deuxième phrase tout aussi longue que la première.")
    assert len(sentences(text)) == 2


def test_keywords_ignore_les_mots_vides():
    words = keywords("Le chiffrement utilise une clé privée pour déchiffrer.")
    assert "chiffrement" in [w.lower() for w in words]
    assert "le" not in [w.lower() for w in words]


def test_flashcards_locales(pdf: Path):
    cards = flashcards_locally(extract_text(pdf), count=5)
    assert len(cards) == 5
    assert all(c["generated_by"] == "rules" for c in cards)
    assert all(c["answer"] for c in cards)
    assert len({c["answer"].lower() for c in cards}) == len(cards)  # pas de doublon
    assert "……" in cards[0]["question"]


def test_quiz_local_a_quatre_options(pdf: Path):
    questions = quiz_locally(extract_text(pdf), count=4)
    assert questions
    for question in questions:
        assert len(question["options"]) == 4
        assert 0 <= question["answer"] < 4
        assert len(set(question["options"])) == 4


def test_generate_sans_cle(pdf: Path):
    result = generate(extract_text(pdf), count=4, kind="quiz")
    assert result["generated_by"] == "rules"
    assert result["kind"] == "quiz"


def test_export_tsv(pdf: Path):
    cards = flashcards_locally(extract_text(pdf), count=3)
    tsv = to_tsv(cards, "flashcards")
    assert tsv.count("\n") == 2
    assert "\t" in tsv


# --------------------------------------------------------------------------- #
# Génération LLM (simulée)
# --------------------------------------------------------------------------- #
def test_flashcards_llm_simule(pdf: Path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: [
        {"question": "Que fait AES ?", "answer": "Il chiffre en symétrique.",
         "tags": ["AES"]}])
    result = generate(extract_text(pdf), count=3)
    assert result["generated_by"] == "llm"
    assert result["items"][0]["question"] == "Que fait AES ?"


def test_quiz_llm_rejette_options_invalides(pdf: Path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: [
        {"question": "Q1", "options": ["a", "b"], "answer": 0},
        {"question": "Q2", "options": ["a", "b", "c", "d"], "answer": 2, "explanation": "e"}])
    result = generate(extract_text(pdf), count=5, kind="quiz")
    assert [q["question"] for q in result["items"]] == ["Q2"]


def test_repli_si_llm_renvoie_none(pdf: Path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: None)
    assert generate(extract_text(pdf), count=3)["generated_by"] == "rules"


# --------------------------------------------------------------------------- #
# CLI et web
# --------------------------------------------------------------------------- #
def test_cli_json(pdf: Path, capsys):
    assert main(["generate", str(pdf), "--count", "4", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["items"]) == 4
    assert payload["chars"] > 100


def test_cli_ecrit_un_fichier(pdf: Path, tmp_path: Path, capsys):
    out = tmp_path / "cartes.tsv"
    assert main(["generate", str(pdf), "--format", "tsv", "--out", str(out)]) == 0
    assert "\t" in out.read_text(encoding="utf-8")


def test_cli_pdf_invalide(tmp_path: Path, capsys):
    bad = tmp_path / "bad.pdf"
    bad.write_text("nope", encoding="utf-8")
    assert main(["generate", str(bad)]) == 2


def test_cli_llm(capsys):
    assert main(["llm"]) == 0
    assert "Fournisseur" in capsys.readouterr().out


def test_parse_multipart():
    boundary = b"X"
    body = (b"--X\r\nContent-Disposition: form-data; name=\"kind\"\r\n\r\nquiz\r\n"
            b"--X\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.pdf\"\r\n"
            b"Content-Type: application/pdf\r\n\r\n%PDF-1.4\r\n--X--\r\n")
    fields = _parse_multipart(body, boundary)
    assert fields["kind"][1] == b"quiz"
    assert fields["file"][0] == "a.pdf"


def test_index_html_contient_les_elements():
    for marker in ("Déposez un PDF", "api/generate", "Flashcards"):
        assert marker in INDEX_HTML
