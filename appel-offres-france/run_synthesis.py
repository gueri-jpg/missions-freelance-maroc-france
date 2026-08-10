"""CLI — Synthèse IA des DCE téléchargés (fournisseur configurable via
LLM_PROVIDER / --provider), mise à jour des colonnes DCE dans l'Excel.

Usage :
    python run_synthesis.py [--provider gemini|anthropic] [--limit N]
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

_DOC_PRIORITY_PATTERNS = (
    (0, ("ccap",)),  # cahier des clauses administratives particulières — pénalités
    (1, ("rc", "reglement", "règlement")),  # règlement de consultation — grille de notation, calendrier
    (2, ("cctp",)),  # cahier des clauses techniques particulières — mission
)


def _document_priority(filename: str) -> int:
    """Rang de priorité (plus petit = prioritaire). RC et CCAP sont
    priorisés en premier car ils concentrent les informations recherchées
    par la synthèse (calendrier, grille de notation, pénalités)."""
    stem = Path(filename).stem.lower()
    tokens = set(re.split(r"[^a-zàâçéèêëîïôûùüÿñæœ0-9]+", stem))
    for rank, patterns in _DOC_PRIORITY_PATTERNS:
        if any(p in tokens or p in stem for p in patterns):
            return rank
    return 99

import config
import excel_writer
from extractor import extract_text
from synthesis_agent import SynthesisError, synthesize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_DIR / "synthesis.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("run_synthesis")


def _safe_dirname(record_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", record_id)


def _pick_document(dest_dir: Path) -> tuple[Path | None, str | None]:
    """Choisit le meilleur document exploitable dans le dossier DCE d'un
    avis. RC (règlement de consultation) et CCAP (cahier des clauses
    administratives particulières) sont priorisés — ils concentrent le
    calendrier, la grille de notation et les pénalités — puis le CCTP, puis
    tout autre PDF. PDF envoyé directement au LLM ; à défaut, texte extrait
    d'un DOCX."""
    if not dest_dir.exists():
        return None, None

    pdfs = sorted(dest_dir.glob("*.pdf"), key=lambda p: _document_priority(p.name))
    if pdfs:
        return pdfs[0], None

    docxs = sorted(dest_dir.glob("*.docx"), key=lambda p: _document_priority(p.name))
    if docxs:
        result = extract_text(docxs[0])
        if result.status == "ok":
            return None, result.text

    return None, None


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthèse IA des DCE téléchargés")
    parser.add_argument("--provider", choices=["gemini", "anthropic"], default=None, help="Fournisseur LLM (défaut : LLM_PROVIDER)")
    parser.add_argument("--model", default=None, help="Force un id de modèle (ex. gemini-2.5-flash-lite pour un quota gratuit séparé de gemini-2.5-flash)")
    parser.add_argument("--limit", type=int, default=20, help="Nombre max d'avis à traiter par exécution")
    args = parser.parse_args()

    if args.model:
        config.GEMINI_MODEL = args.model
        config.ANTHROPIC_MODEL = args.model

    rows = excel_writer.read_main_rows()
    # "ok (...)" = synthèse LLM déjà réussie -> ne pas retraiter.
    # "" (vide) ou "pré-rempli (BOAMP)..." ou "erreur : ..." -> encore
    # éligible (le pré-remplissage BOAMP seul ne couvre pas pénalités/
    # grille/présentiel/références, et une erreur peut être transitoire —
    # ex. quota journalier épuisé, à retenter plus tard ou avec un autre modèle).
    statut_deja_ok = lambda s: bool(s) and s.startswith("ok (")
    todo = [
        r for r in rows
        if r.get("Statut téléchargement") == "téléchargé" and not statut_deja_ok(r.get("Statut synthèse"))
    ]
    logger.info("%d avis en attente de synthèse (limite=%d, provider=%s)", len(todo), args.limit, args.provider or config.LLM_PROVIDER)

    processed = 0
    for row in todo[: args.limit]:
        record_id = str(row["Référence/ID"])
        dest_dir = config.DCE_DIR / _safe_dirname(record_id)
        pdf_path, text = _pick_document(dest_dir)

        if pdf_path is None and not text:
            logger.warning("[%s] Aucun document exploitable dans %s — synthèse ignorée", record_id, dest_dir)
            excel_writer.update_synthesis_columns(record_id, {}, "document non exploitable")
            processed += 1
            continue

        try:
            result = synthesize(pdf_path=pdf_path, text=text, provider=args.provider)
        except SynthesisError as exc:
            logger.error("[%s] Échec synthèse : %s", record_id, exc)
            excel_writer.update_synthesis_columns(record_id, {}, f"erreur : {exc}")
            processed += 1
            continue
        except Exception as exc:  # noqa: BLE001 — une erreur imprévue sur un avis ne doit jamais interrompre tout le lot
            logger.error("[%s] Erreur inattendue : %s", record_id, exc)
            excel_writer.update_synthesis_columns(record_id, {}, f"erreur inattendue : {exc}")
            processed += 1
            continue

        synthese = result.to_dict()
        excel_writer.update_synthesis_columns(record_id, synthese, f"ok ({result.provider})")
        logger.info("[%s] Synthèse OK via %s", record_id, result.provider)
        processed += 1

    logger.info("Traitement terminé : %d avis traités", processed)


if __name__ == "__main__":
    main()
