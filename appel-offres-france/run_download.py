"""CLI — Téléchargement best-effort des DCE pour les avis pertinents
(Domaine "IT confirmé" ou "à vérifier") déjà présents dans l'Excel.

Usage :
    python run_download.py [--limit N]
"""
from __future__ import annotations

import argparse
import logging
import re
import sys

import config
import excel_writer
from downloader import STATUT_TELECHARGE, download_dce

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_DIR / "download.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("run_download")

DOMAINES_PERTINENTS = ("IT confirmé", "à vérifier")


def _safe_dirname(record_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", record_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Téléchargement des DCE pour les avis pertinents")
    parser.add_argument("--limit", type=int, default=50, help="Nombre max d'avis à traiter par exécution")
    parser.add_argument("--save-every", type=int, default=15,
                         help="Sauvegarder l'Excel tous les N avis traités (moins d'ouvertures/fermetures = moins de conflits avec un dossier synchronisé cloud)")
    args = parser.parse_args()

    rows = excel_writer.read_main_rows()
    todo = [
        r for r in rows
        if r.get("Domaine") in DOMAINES_PERTINENTS and r.get("Statut téléchargement") != STATUT_TELECHARGE
    ]
    logger.info("%d avis pertinents en attente de téléchargement (limite=%d)", len(todo), args.limit)

    # Mise à jour groupée du statut plutôt qu'une ouverture/sauvegarde du
    # classeur par avis : réduit fortement le risque de conflit avec la
    # synchronisation cloud (OneDrive) ou une instance Excel ouverte.
    pending_statuses: dict[str, str] = {}

    def _flush() -> None:
        if not pending_statuses:
            return
        n = excel_writer.update_download_status_bulk(pending_statuses)
        logger.info("Excel mis à jour : %d statut(s) enregistré(s)", n)
        pending_statuses.clear()

    processed = 0
    for row in todo[: args.limit]:
        record_id = str(row["Référence/ID"])
        profil_url = row.get("Lien profil acheteur/DCE")
        avis_url = row.get("Lien avis")
        dest_dir = config.DCE_DIR / _safe_dirname(record_id)

        result = None
        if profil_url:
            logger.info("[%s] Téléchargement depuis le profil acheteur : %s", record_id, profil_url)
            result = download_dce(profil_url, dest_dir, reference=record_id)
            logger.info("[%s] Statut (profil acheteur) : %s (%s) — %d fichier(s)",
                        record_id, result.status, result.note, len(result.files))

        # Repli : le PDF de l'avis BOAMP est public (DILA, sans authentification)
        # et fonctionne même quand la plateforme de l'acheteur exige un compte.
        # Ce n'est PAS le DCE complet (RC/CCAP souvent absents de l'avis).
        if (result is None or result.status != STATUT_TELECHARGE) and avis_url and avis_url != profil_url:
            logger.info("[%s] Repli sur l'avis BOAMP (document public) : %s", record_id, avis_url)
            avis_result = download_dce(avis_url, dest_dir, reference=f"{record_id}_avis")
            if avis_result.status == STATUT_TELECHARGE:
                avis_result.note = "avis BOAMP uniquement — DCE complet (RC/CCAP) non accessible sans compte"
                result = avis_result
            elif result is None:
                result = avis_result

        if result is None:
            logger.warning("[%s] Aucun lien disponible (ni profil acheteur, ni avis)", record_id)
            continue

        logger.info("[%s] Statut final : %s (%s) — %d fichier(s)", record_id, result.status, result.note, len(result.files))
        pending_statuses[record_id] = result.status
        processed += 1

        if processed % args.save_every == 0:
            _flush()

    _flush()
    logger.info("Traitement terminé : %d avis traités", processed)


if __name__ == "__main__":
    main()
