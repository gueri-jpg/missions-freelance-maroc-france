"""CLI — Collecte des avis BOAMP + projets APProch, filtrage/classification,
écriture dans l'Excel de veille.

Usage :
    python run_collect.py [--adaptee] [--max-records N] [--discover]
    python run_collect.py --discover      # log la structure réelle d'un avis BOAMP
"""
from __future__ import annotations

import argparse
import logging
import sys

import collector_approch
import collector_boamp
import collector_place
import config
import excel_writer
from filter_classify import filter_and_classify, filter_and_classify_approch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_DIR / "collect.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("run_collect")


def run_discover() -> None:
    """Découverte des champs BOAMP en réel (section 1 du cahier des
    charges) : appelle records?limit=1 et logue toutes les clés."""
    payload = collector_boamp.discover_fields(limit=1)
    logger.info("total_count BOAMP : %s", payload.get("total_count"))
    if payload.get("results"):
        record = payload["results"][0]
        logger.info("Clés racine : %s", sorted(record.keys()))
        all_keys = collector_boamp.list_all_keys(record)
        logger.info("Toutes les clés (racine + gestion + donnees), %d au total :", len(all_keys))
        for key in all_keys:
            logger.info("  %s", key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collecte des appels d'offres publics IT (BOAMP + APProch)")
    parser.add_argument("--adaptee", action="store_true", help="Ne garder que les procédures adaptées (MAPA)")
    parser.add_argument("--max-records", type=int, default=500, help="Nombre max d'avis BOAMP à collecter")
    parser.add_argument("--max-records-approch", type=int, default=300, help="Nombre max de projets APProch à collecter")
    parser.add_argument("--skip-approch", action="store_true", help="Ne pas interroger l'API APProch")
    parser.add_argument("--skip-place", action="store_true",
                         help="Ne pas scraper PLACE/Maximilien (profils acheteurs complémentaires)")
    parser.add_argument("--max-records-place", type=int, default=200,
                         help="Nombre max d'avis par plateforme PLACE/Maximilien à collecter")
    parser.add_argument("--discover", action="store_true", help="Log la structure réelle des champs BOAMP puis quitte")
    args = parser.parse_args()

    if args.discover:
        run_discover()
        return

    logger.info("Collecte BOAMP (mots-clés=%d, adaptee_only=%s, max=%d)...",
                len(config.MOTS_CLES_IT), args.adaptee, args.max_records)
    boamp_records = collector_boamp.collect(
        keywords=config.MOTS_CLES_IT,
        adaptee_only=args.adaptee,
        max_records=args.max_records,
    )
    logger.info("BOAMP : %d avis récupérés avant classification", len(boamp_records))

    classified = filter_and_classify(boamp_records, adaptee_only=args.adaptee)
    logger.info("BOAMP : %d avis après filtrage accord-cadre/procédure", len(classified))

    domain_counts = {}
    for r in classified:
        domain_counts[r["domaine"]] = domain_counts.get(r["domaine"], 0) + 1
    logger.info("Répartition par domaine : %s", domain_counts)

    added, updated = excel_writer.write_records(classified)
    logger.info("Excel (onglet principal) : %d ajoutés, %d mis à jour -> %s", added, updated, config.EXCEL_PATH)

    if not args.skip_place:
        logger.info("Collecte PLACE/Maximilien (profils acheteurs complémentaires, sans compte)...")
        try:
            place_records = collector_place.collect_all_platforms(max_records_per_platform=args.max_records_place)
            logger.info("PLACE/Maximilien : %d avis récupérés avant classification", len(place_records))

            place_classified = filter_and_classify(place_records, adaptee_only=True)
            logger.info("PLACE/Maximilien : %d avis après filtrage/classification", len(place_classified))

            place_domain_counts = {}
            for r in place_classified:
                place_domain_counts[r["domaine"]] = place_domain_counts.get(r["domaine"], 0) + 1
            logger.info("PLACE/Maximilien — répartition par domaine : %s", place_domain_counts)

            added_p, updated_p = excel_writer.write_records(place_classified)
            logger.info("Excel (onglet principal) : %d ajoutés, %d mis à jour (PLACE/Maximilien)", added_p, updated_p)
        except collector_place.PlaceError as exc:
            logger.error("Échec collecte PLACE/Maximilien (non bloquant) : %s", exc)

    if not args.skip_approch:
        logger.info("Collecte APProch (prévisionnel, non exhaustif)...")
        try:
            approch_records = collector_approch.collect(
                keywords=config.MOTS_CLES_IT,
                max_records=args.max_records_approch,
            )
            logger.info("APProch : %d projets récupérés avant classification", len(approch_records))

            approch_classified = filter_and_classify_approch(approch_records)
            logger.info(
                "APProch : %d projets après filtrage montant (<%.0f€)/catégorie d'achat",
                len(approch_classified), config.SEUIL_MONTANT_MAX,
            )

            approch_domain_counts = {}
            for r in approch_classified:
                approch_domain_counts[r["domaine"]] = approch_domain_counts.get(r["domaine"], 0) + 1
            logger.info("APProch — répartition par domaine : %s", approch_domain_counts)

            added_a, updated_a = excel_writer.write_approch_records(approch_classified)
            logger.info("Excel (onglet APProch) : %d ajoutés, %d mis à jour", added_a, updated_a)
        except collector_approch.ApprochError as exc:
            logger.error("Échec collecte APProch (non bloquant) : %s", exc)


if __name__ == "__main__":
    main()
