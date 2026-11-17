"""Serveur web (bibliothèque standard) : interface + API pour pdf-quiz."""
from __future__ import annotations

import html
import json
import re
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import llm
from .generate import generate, to_tsv
from .pdf_text import PDFError, extract_text

MAX_UPLOAD = 12 * 1024 * 1024  # 12 Mo

INDEX_HTML = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PDF → Flashcards & Quiz</title>
<style>
  :root {
    --bg: #0f1115; --panel: #171a21; --line: #262b36; --text: #e6e8ee;
    --muted: #98a0b3; --accent: #6ea8fe; --ok: #3fb950; --bad: #f85149;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif;
         background: var(--bg); color: var(--text); }
  header { padding: 28px 24px 12px; max-width: 980px; margin: 0 auto; }
  h1 { font-size: 24px; margin: 0 0 6px; letter-spacing: -0.02em; }
  .sub { color: var(--muted); font-size: 14px; }
  main { max-width: 980px; margin: 0 auto; padding: 12px 24px 64px; }
  .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
           padding: 18px; margin-bottom: 18px; }
  .drop { border: 2px dashed var(--line); border-radius: 12px; padding: 28px;
          text-align: center; color: var(--muted); transition: .15s; cursor: pointer; }
  .drop.over { border-color: var(--accent); color: var(--text); background: #1b2130; }
  .row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-top: 14px; }
  input[type=number] { width: 76px; background: #0d1017; color: var(--text);
                       border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
  select { background: #0d1017; color: var(--text); border: 1px solid var(--line);
           border-radius: 8px; padding: 8px; }
  button { background: var(--accent); color: #07101f; border: 0; border-radius: 8px;
           padding: 9px 16px; font-weight: 600; cursor: pointer; }
  button.ghost { background: transparent; color: var(--text); border: 1px solid var(--line); }
  button:disabled { opacity: .5; cursor: progress; }
  .badge { font-size: 12px; color: var(--muted); border: 1px solid var(--line);
           border-radius: 999px; padding: 3px 10px; }
  .card { background: #12151c; border: 1px solid var(--line); border-radius: 10px;
          padding: 14px 16px; margin-bottom: 10px; cursor: pointer; }
  .card .a { display: none; margin-top: 8px; color: var(--ok); }
  .card.open .a { display: block; }
  .q { font-weight: 600; }
  .opt { display: block; padding: 7px 10px; border-radius: 8px; margin: 5px 0;
         border: 1px solid var(--line); cursor: pointer; }
  .opt:hover { border-color: var(--accent); }
  .opt.good { border-color: var(--ok); color: var(--ok); }
  .opt.bad { border-color: var(--bad); color: var(--bad); }
  .exp { color: var(--muted); font-size: 13px; margin-top: 6px; }
  .err { color: var(--bad); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; }
  footer { color: var(--muted); font-size: 12px; text-align: center; padding: 24px; }
</style>
</head>
<body>
<header>
  <h1>PDF → Flashcards & Quiz</h1>
  <div class="sub">Importez un cours au format PDF, l'IA le transforme en cartes de révision
    et en QCM. Traitement local, aucun envoi de fichier vers un tiers.</div>
</header>
<main>
  <div class="panel">
    <div class="drop" id="drop">
      <strong>Déposez un PDF ici</strong><br>ou cliquez pour choisir un fichier
      <input type="file" id="file" accept="application/pdf" hidden>
    </div>
    <div class="row">
      <label>Type
        <select id="kind">
          <option value="flashcards">Flashcards</option>
          <option value="quiz">Quiz QCM</option>
        </select>
      </label>
      <label>Nombre <input type="number" id="count" value="10" min="3" max="40"></label>
      <button id="go" disabled>Générer</button>
      <button class="ghost" id="export" disabled>Exporter (.tsv Anki)</button>
      <span class="badge" id="engine">moteur : —</span>
    </div>
    <div id="status" class="sub" style="margin-top:12px"></div>
  </div>
  <div id="result"></div>
</main>
<footer>pdf-quiz · fonctionne hors ligne (gabarits) ou avec Claude / OpenAI / Ollama</footer>
<script>
const drop = document.getElementById('drop');
const fileInput = document.getElementById('file');
const go = document.getElementById('go');
const statusEl = document.getElementById('status');
const resultEl = document.getElementById('result');
const engineEl = document.getElementById('engine');
const exportBtn = document.getElementById('export');
let current = null, currentKind = 'flashcards', fileName = '';

fetch('/api/status').then(r => r.json()).then(s => {
  engineEl.textContent = 'moteur : ' + (s.available ? s.provider : 'règles locales');
});

function pick(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    statusEl.innerHTML = '<span class="err">Fichier PDF attendu.</span>'; return;
  }
  fileName = file.name;
  go.disabled = false;
  statusEl.textContent = fileName + ' — prêt à générer';
}

drop.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => pick(fileInput.files[0]));
['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault(); drop.classList.add('over');
}));
['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault(); drop.classList.remove('over');
}));
drop.addEventListener('drop', e => pick(e.dataTransfer.files[0]));

go.addEventListener('click', async () => {
  const file = fileInput.files[0];
  if (!file) return;
  go.disabled = true;
  statusEl.textContent = 'Analyse du PDF et génération…';
  resultEl.innerHTML = '';
  const form = new FormData();
  form.append('file', file);
  form.append('kind', document.getElementById('kind').value);
  form.append('count', document.getElementById('count').value);
  try {
    const res = await fetch('/api/generate', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'erreur serveur');
    current = data;
    currentKind = data.kind;
    engineEl.textContent = 'moteur : ' + (data.generated_by === 'llm' ? 'IA' : 'règles locales');
    statusEl.textContent = data.items.length + ' élément(s) générés depuis ' +
                           data.chars + ' caractères de texte';
    render(data);
    exportBtn.disabled = false;
  } catch (err) {
    statusEl.innerHTML = '<span class="err">' + err.message + '</span>';
  } finally {
    go.disabled = false;
  }
});

function render(data) {
  resultEl.innerHTML = '';
  if (data.kind === 'flashcards') {
    const grid = document.createElement('div');
    grid.className = 'grid';
    data.items.forEach((card, i) => {
      const el = document.createElement('div');
      el.className = 'card';
      el.innerHTML = '<div class="q">' + (i + 1) + '. ' + esc(card.question) + '</div>' +
                     '<div class="a">' + esc(card.answer) + '</div>';
      el.addEventListener('click', () => el.classList.toggle('open'));
      grid.appendChild(el);
    });
    resultEl.appendChild(grid);
  } else {
    data.items.forEach((q, i) => {
      const el = document.createElement('div');
      el.className = 'panel';
      let html = '<div class="q">' + (i + 1) + '. ' + esc(q.question) + '</div>';
      q.options.forEach((opt, idx) => {
        html += '<span class="opt" data-idx="' + idx + '">' + 'ABCD'[idx] + '. ' +
                esc(opt) + '</span>';
      });
      html += '<div class="exp" hidden>' + esc(q.explanation) + '</div>';
      el.innerHTML = html;
      el.querySelectorAll('.opt').forEach(node => {
        node.addEventListener('click', () => {
          const idx = Number(node.dataset.idx);
          el.querySelectorAll('.opt').forEach(n => n.classList.remove('good', 'bad'));
          node.classList.add(idx === q.answer ? 'good' : 'bad');
          if (idx !== q.answer) {
            el.querySelector('.opt[data-idx="' + q.answer + '"]').classList.add('good');
          }
          el.querySelector('.exp').hidden = false;
        });
      });
      resultEl.appendChild(el);
    });
  }
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

exportBtn.addEventListener('click', () => {
  if (!current) return;
  const blob = new Blob([current.tsv], { type: 'text/tab-separated-values' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName.replace(/\\.pdf$/i, '') + '-' + currentKind + '.tsv';
  a.click();
  URL.revokeObjectURL(url);
});
</script>
</body>
</html>
"""


def _parse_multipart(body: bytes, boundary: bytes) -> dict[str, tuple[str, bytes]]:
    """Analyse un corps multipart/form-data (stdlib uniquement)."""
    fields: dict[str, tuple[str, bytes]] = {}
    for part in body.split(b"--" + boundary):
        if b"\r\n\r\n" not in part:
            continue
        head, data = part.split(b"\r\n\r\n", 1)
        data = data.rstrip(b"\r\n-")
        name_match = re.search(rb'name="([^"]+)"', head)
        if not name_match:
            continue
        name = name_match.group(1).decode()
        filename_match = re.search(rb'filename="([^"]*)"', head)
        filename = filename_match.group(1).decode() if filename_match else ""
        fields[name] = (filename, data)
    return fields


def create_handler(root: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "pdf-quiz/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:  # silence
            return

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data: dict) -> None:
            self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json")

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, INDEX_HTML.encode(), "text/html; charset=utf-8")
            elif path == "/api/status":
                self._json(200, llm.status())
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/generate":
                self._json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD:
                self._json(413, {"error": "fichier trop volumineux (12 Mo max)"})
                return
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                self._json(400, {"error": "multipart/form-data attendu"})
                return
            boundary = content_type.split("boundary=", 1)[-1].encode()
            fields = _parse_multipart(self.rfile.read(length), boundary)
            if "file" not in fields:
                self._json(400, {"error": "aucun fichier reçu"})
                return

            filename, data = fields["file"]
            kind = fields.get("kind", ("", b"flashcards"))[1].decode() or "flashcards"
            try:
                count = int(fields.get("count", ("", b"10"))[1].decode() or 10)
            except ValueError:
                count = 10
            count = max(3, min(count, 40))

            tmp = Path(tempfile.gettempdir()) / f"pdf-quiz-{abs(hash(filename))}.pdf"
            tmp.write_bytes(data)
            try:
                text = extract_text(tmp)
            except PDFError as exc:
                self._json(422, {"error": str(exc)})
                return
            finally:
                tmp.unlink(missing_ok=True)

            result = generate(text, count=count, kind=kind)
            payload = {
                "kind": result["kind"],
                "generated_by": result["generated_by"],
                "chars": len(text),
                "items": result["items"],
                "tsv": to_tsv(result["items"], result["kind"]),
            }
            self._json(200, payload)

    return Handler


def serve(root: Path | None = None, host: str = "127.0.0.1", port: int = 8770) -> None:
    handler = create_handler(root or Path.cwd())
    server = ThreadingHTTPServer((host, port), handler)
    print(f"pdf-quiz → http://{host}:{port}  (Ctrl+C pour arrêter)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def html_escape(text: str) -> str:
    return html.escape(text)
