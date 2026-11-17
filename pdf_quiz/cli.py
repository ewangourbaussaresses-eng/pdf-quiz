"""CLI de pdf-quiz : génère flashcards / quiz depuis un PDF."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, llm
from .generate import generate, to_tsv
from .pdf_text import PDFError, extract_text
from .web import serve


def command_generate(args: argparse.Namespace) -> int:
    try:
        text = extract_text(args.pdf)
    except PDFError as exc:
        print(f"✖ {exc}", file=sys.stderr)
        return 2

    result = generate(text, count=args.count, kind=args.kind, use_llm=not args.no_llm)
    if not result["items"]:
        print("✖ aucun contenu généré (texte trop court ou trop pauvre)", file=sys.stderr)
        return 1

    if args.format == "json":
        payload = {"kind": result["kind"], "generated_by": result["generated_by"],
                   "chars": len(text), "items": result["items"]}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.format == "tsv":
        print(to_tsv(result["items"], result["kind"]))
    elif args.format == "markdown":
        lines = [f"# {'Flashcards' if result['kind'] == 'flashcards' else 'Quiz'} — "
                 f"{Path(args.pdf).stem}", ""]
        for index, item in enumerate(result["items"], 1):
            if result["kind"] == "flashcards":
                lines += [f"**{index}. {item['question']}**", "", item["answer"], ""]
            else:
                lines += [f"**{index}. {item['question']}**", ""]
                lines += [f"- {'ABCD'[i]}. {opt}" for i, opt in enumerate(item["options"])]
                lines += ["", f"*Réponse : {'ABCD'[item['answer']]}* — "
                              f"{item['explanation']}", ""]
        print("\n".join(lines))

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        if args.format == "json":
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        elif args.format == "tsv":
            out.write_text(to_tsv(result["items"], result["kind"]), encoding="utf-8")
        else:
            out.write_text("\n".join(f"{i['question']}\t{i.get('answer', '')}"
                                     for i in result["items"]), encoding="utf-8")
        print(f"✔ écrit : {out}", file=sys.stderr)
    return 0


def command_serve(args: argparse.Namespace) -> int:
    serve(port=args.port, host=args.host)
    return 0


def command_llm(args: argparse.Namespace) -> int:
    info = llm.status()
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    print(f"Fournisseur : {info['provider']} "
          f"({'connecté' if info['available'] else 'non configuré'})")
    if info["model"]:
        print(f"Modèle      : {info['model']}")
    if not info["available"]:
        print("→ Sans clé, la génération utilise les règles locales (hors ligne).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-quiz",
        description="Transforme un PDF de cours en flashcards ou en QCM.")
    parser.add_argument("--version", action="version", version=f"pdf-quiz {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="générer depuis un PDF")
    gen.add_argument("pdf", help="chemin du PDF")
    gen.add_argument("--kind", choices=["flashcards", "quiz"], default="flashcards")
    gen.add_argument("--count", type=int, default=10, help="nombre d'éléments (3-40)")
    gen.add_argument("--format", choices=["text", "json", "tsv", "markdown"],
                     default="text", help="format de sortie")
    gen.add_argument("--out", help="fichier de sortie")
    gen.add_argument("--no-llm", action="store_true", help="forcer les règles locales")
    gen.set_defaults(func=command_generate)

    web = sub.add_parser("serve", help="lancer l'interface web")
    web.add_argument("--port", type=int, default=8770)
    web.add_argument("--host", default="127.0.0.1")
    web.set_defaults(func=command_serve)

    llm_cmd = sub.add_parser("llm", help="état du connecteur IA")
    llm_cmd.add_argument("--json", action="store_true")
    llm_cmd.set_defaults(func=command_llm)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "count", 0):
        args.count = max(3, min(args.count, 40))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
