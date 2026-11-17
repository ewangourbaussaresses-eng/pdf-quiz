"""Génération de flashcards et de quiz depuis un texte (LLM ou règles locales)."""
from __future__ import annotations

import re
from typing import Any

from . import llm
from .pdf_text import chunk_text

FLASHCARD_SYSTEM = (
    "Tu es un professeur qui prépare des révisions. Tu produis des cartes mémoires "
    "précises, fondées UNIQUEMENT sur le texte fourni. Jamais d'invention. "
    "Tu réponds UNIQUEMENT en JSON."
)

QUIZ_SYSTEM = (
    "Tu es un professeur qui rédige un QCM à partir d'un cours. Chaque question a une "
    "seule bonne réponse, trois distracteurs plausibles et une explication courte. "
    "Tu n'inventes aucun fait absent du texte. Tu réponds UNIQUEMENT en JSON."
)

STOPWORDS = set("""
le la les un une des du de d au aux et ou mais donc or ni car que qui quoi dont où
ce cet cette ces son sa ses leur leurs il elle ils elles on nous vous je tu se s
est sont être avoir a ont dans pour par sur avec sans sous entre chez vers plus moins
très trop peu tout tous toute toutes autre autres même aussi comme si non oui
l' d' qu' c' n' j' m' t' s' y
""".split())


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 30]


def keywords(sentence: str, limit: int = 4) -> list[str]:
    words = re.findall(r"[A-Za-zÀ-ÿ][\wÀ-ÿ\-]{3,}", sentence)
    scored = [w for w in words if w.lower() not in STOPWORDS]
    # les mots « techniques » (majuscules, tirets, chiffres) d'abord
    scored.sort(key=lambda w: (-(w.isupper() or "-" in w or any(c.isdigit() for c in w)),
                               -len(w)))
    seen: list[str] = []
    for word in scored:
        if word.lower() not in {s.lower() for s in seen}:
            seen.append(word)
    return seen[:limit]


# --------------------------------------------------------------------------- #
# Mode règles
# --------------------------------------------------------------------------- #
def flashcards_locally(text: str, count: int = 10) -> list[dict[str, Any]]:
    """Cartes « compléter la phrase » : question sans le terme clé, réponse = terme."""
    cards: list[dict[str, Any]] = []
    used_terms: set[str] = set()
    for sentence in sentences(text):
        words = keywords(sentence)
        if len(words) < 2:
            continue
        term = next((w for w in words if w.lower() not in used_terms), None)
        if term is None:
            continue
        used_terms.add(term.lower())
        # masque le terme dans la phrase pour construire la question
        masked = re.sub(rf"\b{re.escape(term)}\b", "……", sentence, count=1)
        cards.append({
            "question": f"Complétez : {masked}",
            "answer": term,
            "tags": [term],
            "context": sentence if len(sentence) <= 220 else sentence[:217] + "…",
            "generated_by": "rules",
        })
        if len(cards) >= count:
            break
    return cards


def quiz_locally(text: str, count: int = 5) -> list[dict[str, Any]]:
    pool = [s for s in sentences(text) if len(s) >= 60 and len(keywords(s)) >= 3]
    questions: list[dict[str, Any]] = []
    for index, sentence in enumerate(pool[:count]):
        words = keywords(sentence)
        if not words:
            continue
        answer = words[0]
        others = [w for s in pool for w in keywords(s) if w.lower() != answer.lower()]
        distractors: list[str] = []
        for word in others:
            if word.lower() not in {d.lower() for d in distractors} and word != answer:
                distractors.append(word)
            if len(distractors) == 3:
                break
        if len(distractors) < 3:
            continue
        options = [answer, *distractors]
        # rotation déterministe pour que la bonne réponse ne soit pas toujours en tête
        shift = index % 4
        options = options[shift:] + options[:shift]
        questions.append({
            "question": f"Dans le cours, quel terme est associé à : « {sentence[:110]}… » ?",
            "options": options,
            "answer": options.index(answer),
            "explanation": sentence[:200],
            "generated_by": "rules",
        })
    return questions


# --------------------------------------------------------------------------- #
# Mode LLM
# --------------------------------------------------------------------------- #
def flashcards_with_llm(text: str, count: int = 10) -> list[dict[str, Any]] | None:
    chunks = chunk_text(text, size=4000, overlap=0)
    if not chunks:
        return None
    per_chunk = max(3, count // len(chunks) + 1)
    cards: list[dict[str, Any]] = []
    for chunk in chunks[:5]:
        prompt = f"""À partir de ce cours, produis {per_chunk} cartes mémoires.

Cours :
\"\"\"{chunk}\"\"\"

Réponds uniquement avec ce JSON :
[{{"question": "question courte et précise",
   "answer": "réponse de 1 à 3 phrases",
   "tags": ["mot-clé"]}}]"""
        data = llm.ask_json(prompt, system=FLASHCARD_SYSTEM, max_tokens=1500,
                            temperature=0.3)
        if not isinstance(data, list):
            return None
        for item in data:
            if isinstance(item, dict) and item.get("question") and item.get("answer"):
                cards.append({
                    "question": str(item["question"]).strip(),
                    "answer": str(item["answer"]).strip(),
                    "tags": [str(t) for t in (item.get("tags") or [])][:4],
                    "generated_by": "llm",
                })
        if len(cards) >= count:
            break
    return cards[:count] or None


def quiz_with_llm(text: str, count: int = 5) -> list[dict[str, Any]] | None:
    chunk = chunk_text(text, size=6000, overlap=0)
    if not chunk:
        return None
    prompt = f"""À partir de ce cours, écris un QCM de {count} questions.

Cours :
\"\"\"{chunk[0]}\"\"\"

Contraintes :
- 4 options par question, une seule correcte ;
- l'index de la bonne réponse varie d'une question à l'autre ;
- explication d'une phrase.

Réponds uniquement avec ce JSON :
[{{"question": "…", "options": ["a", "b", "c", "d"], "answer": 0, "explanation": "…"}}]"""
    data = llm.ask_json(prompt, system=QUIZ_SYSTEM, max_tokens=2000, temperature=0.4)
    if not isinstance(data, list):
        return None
    questions: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        options = [str(o) for o in (item.get("options") or [])]
        answer = item.get("answer")
        if len(options) != 4 or not isinstance(answer, int) or not 0 <= answer < 4:
            continue
        questions.append({
            "question": str(item.get("question", "")).strip(),
            "options": options,
            "answer": answer,
            "explanation": str(item.get("explanation", "")).strip(),
            "generated_by": "llm",
        })
    return questions[:count] or None


def generate(text: str, count: int = 10, kind: str = "flashcards",
             use_llm: bool = True) -> dict[str, Any]:
    """Produit des flashcards ou un quiz, avec repli local."""
    if use_llm and llm.is_available():
        cards = (flashcards_with_llm(text, count) if kind == "flashcards"
                 else quiz_with_llm(text, count))
        if cards:
            return {"kind": kind, "items": cards, "generated_by": "llm"}
    items = (flashcards_locally(text, count) if kind == "flashcards"
             else quiz_locally(text, count))
    return {"kind": kind, "items": items, "generated_by": "rules"}


def to_tsv(items: list[dict[str, Any]], kind: str) -> str:
    """Export Anki : front<TAB>back."""
    lines = []
    for item in items:
        if kind == "flashcards":
            front, back = item["question"], item["answer"]
        else:
            options = " | ".join(f"{chr(65 + i)}. {o}" for i, o in enumerate(item["options"]))
            front = item["question"] + "\\n" + options
            back = f"Réponse {chr(65 + item['answer'])} — {item['explanation']}"
        lines.append(f"{front.replace(chr(9), ' ')}\t{back.replace(chr(9), ' ')}")
    return "\n".join(lines)
