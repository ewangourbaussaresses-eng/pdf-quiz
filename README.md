# 🧠 pdf-quiz

**Importez un cours en PDF, obtenez des flashcards et un QCM en quelques secondes.**

Interface web (glisser-déposer) + CLI. Aucune dépendance obligatoire, aucun envoi de
fichier vers un service tiers : le PDF est lu localement, seul le texte extrait part
vers le modèle d'IA si vous en configurez un.

---

## Fonctionnalités

- lecture de PDF **sans dépendance** (texte natif, flux compressés) ;
- **flashcards** interactives : cliquez pour révéler la réponse ;
- **QCM** avec correction immédiate et explication ;
- export **`.tsv` compatible Anki** (front ↔ back) ;
- génération par **IA** (Claude, OpenAI ou Ollama local) ou par **règles locales** hors ligne ;
- CLI : `--format json|tsv|markdown`, écriture de fichier, `--no-llm`.

## Installation

```bash
git clone <url-du-depot>
cd pdf-quiz
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

Python 3.9+, aucune dépendance.

## Utilisation

### Interface web

```bash
pdf-quiz serve            # http://127.0.0.1:8770
```

Déposez un PDF, choisissez *Flashcards* ou *Quiz QCM*, cliquez sur **Générer**.
Le bouton **Exporter (.tsv Anki)** télécharge les cartes.

### Ligne de commande

```bash
# 10 flashcards
pdf-quiz generate cours.pdf

# 12 questions de QCM, en markdown
pdf-quiz generate cours.pdf --kind quiz --count 12 --format markdown

# export Anki
pdf-quiz generate cours.pdf --format tsv --out cartes.tsv

# sans IA (règles locales)
pdf-quiz generate cours.pdf --no-llm
```

Un PDF d'exemple est fourni : `samples/cours-chiffrement.pdf`.

## Brancher une IA

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # Claude (recommandé)
# ou
export OPENAI_API_KEY="sk-..."
# ou, 100 % local :
export OLLAMA_MODEL="llama3.2"          # ollama serve doit tourner
```

Vérification : `pdf-quiz llm`. Sans clé, la génération utilise les règles locales
(phrases à compléter, QCM à quatre options construites à partir du texte).

## Limites

- Les **PDF scannés** (images sans couche texte) ne sont pas lisibles : il faut un OCR
  (par ex. `ocrmypdf`) avant de les passer à `pdf-quiz`. L'outil le signale clairement.
- Le mode règles produit des cartes mécaniques ; le mode IA est nettement meilleur.
- Les tableaux et les formules mathématiques sont mal restitués (limite de l'extraction
  texte de PDF).

## Tests

```bash
python -m pytest -q     # 21 tests, aucun accès réseau (PDF généré à la volée)
```

## Licence

MIT — voir [LICENSE](LICENSE).
