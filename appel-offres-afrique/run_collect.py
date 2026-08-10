"""CLI — Collecte des avis IT (DGMP Côte d'Ivoire + PMMP Maroc + BCEAO + BAD),
filtrage/classification, écriture dans l'Excel de veille Afrique.

PPM Côte d'Ivoire (plans prévisionnels) retiré du pipeline — demandé
explicitement (05/08/2026) : contenu majoritairement hors du domaine métier
réel (camions bennes, forages, électricité de bâtiment, mobilier scolaire...)
faute de pré-filtre par mots-clés côté collecteur, et dates prévisionnelles
structurellement déjà anciennes de plusieurs mois à la publication (cf.
`collector_ci_ppm.py`, conservé sur disque mais non importé/appelé ici).

Usage :
    python run_collect.py [--skip-ci] [--skip-maroc] [--maroc-max-pages N]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

import collector_bad
import collector_bceao
import collector_ci
import collector_maroc
import collector_maroc_pps
import collector_onda
import config
import excel_writer
from filter_classify import classify_domain, filter_and_classify, is_deadline_too_soon, is_montant_too_high

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_DIR / "collect.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("run_collect")


def _write_or_cache(write_fn, records: list[dict], label: str, source: str | set[str] | None = None) -> None:
    """Écrit dans l'Excel ; en cas d'échec (fichier ouvert dans Excel,
    verrouillé par une synchronisation cloud...), sauvegarde les données déjà
    collectées dans un cache JSON plutôt que de les perdre — le scraping
    réseau (plusieurs minutes, en particulier PMMP + enrichissement) ne doit
    jamais être refait juste pour un fichier verrouillé au moment d'écrire.

    `source` (transmis à write_fn) déclare explicitement la source à
    synchroniser pour le nettoyage des lignes obsolètes — nécessaire même
    quand `records` est vide (une source qui retombe à 0 avis doit quand
    même pouvoir nettoyer ses anciennes lignes)."""
    try:
        added, updated = write_fn(records, source=source)
        logger.info("Excel : %d ajoutés, %d mis à jour (%s)", added, updated, label)
    except OSError as exc:
        cache_path = config.DATA_DIR / f"cache_non_ecrit_{label.replace(' ', '_')}.json"
        cache_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.error(
            "Échec écriture Excel pour %s (non bloquant) : %s — %d ligne(s) sauvegardées dans %s "
            "(fermez le fichier Excel puis relancez pour les intégrer sans refaire la collecte)",
            label, exc, len(records), cache_path,
        )


def _log_domain_counts(label: str, records: list[dict]) -> None:
    counts: dict[str, int] = {}
    for r in records:
        counts[r["domaine"]] = counts.get(r["domaine"], 0) + 1
    logger.info("%s — répartition par domaine : %s", label, counts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collecte des appels d'offres publics IT — Côte d'Ivoire / Maroc")
    parser.add_argument("--skip-ci", action="store_true", help="Ne pas collecter la source DGMP-CI (avis actifs)")
    parser.add_argument("--skip-maroc", action="store_true", help="Ne pas collecter la source PMMP (Maroc)")
    parser.add_argument("--skip-maroc-pps", action="store_true",
                         help="Ne pas collecter le programme prévisionnel PMMP (Maroc, best-effort)")
    parser.add_argument("--include-onda", action="store_true",
                         help="Collecter aussi les avis ONDA (Maroc, désactivé par défaut). Constaté en "
                              "direct le 05/08/2026 : sur les 14 avis 'en cours' de cette source, 0 "
                              "survivent au filtre une fois les règles de scope correctement appliquées "
                              "(flux structurellement dominé par l'infrastructure/facilities d'un "
                              "exploitant aéroportuaire — gardiennage, nettoyage, travaux, formation — "
                              "pas par du conseil/dev/BI). Gardé opt-in plutôt que supprimé : le code est "
                              "testé et sans risque de fausse donnée depuis ce correctif, au cas où "
                              "l'ONDA publierait un jour un avis réellement dans le scope.")
    parser.add_argument("--skip-bceao", action="store_true",
                         help="Ne pas collecter les avis BCEAO (régional UEMOA — Bénin, Burkina, Côte "
                              "d'Ivoire, Guinée-Bissau, Mali, Niger, Sénégal, Togo). Vérifié en direct : "
                              "page publique sans compte, ~1 avis/jour, aucune clause anti-scraping. Ne "
                              "pas confondre avec 'appels d'offres' du marché monétaire (bons du Trésor, "
                              "injections de liquidité) — hors scope, non collectés.")
    parser.add_argument("--skip-bceao-enrichment", action="store_true",
                         help="Ne pas récupérer le lien DCE par avis BCEAO (une requête supplémentaire "
                              "par avis candidat — désactiver pour un run plus rapide)")
    parser.add_argument("--skip-bad", action="store_true",
                         help="Ne pas collecter les avis BAD/AfDB (siège Abidjan, 2 flux RSS : projets "
                              "financés — filtré Côte d'Ivoire — et achats internes 'corporate', non "
                              "filtrés par pays). Zéro inscription. ATTENTION — limite connue : les "
                              "mots-clés d'exclusion sont en français, une partie des avis BAD sont en "
                              "anglais uniquement ('Cleaning Services' ne matche pas 'nettoyage') — cf. "
                              "README.")
    parser.add_argument("--bad-country-filter", default="Côte d'Ivoire",
                         help="Pays utilisé pour filtrer le flux BAD 'projets' (panafricain par nature)")
    parser.add_argument("--skip-bad-enrichment", action="store_true",
                         help="Ne pas récupérer la date limite réelle par avis BAD (absente du flux RSS "
                              "lui-même, une requête supplémentaire par avis candidat)")
    parser.add_argument("--maroc-max-pages", type=int, default=40,
                         help="Nombre max de pages PMMP à parcourir (10 avis/page). Constaté en direct : "
                              "le portail interrompt la pagination (lien 'page suivante' disparu, ou "
                              "navigation en échec) systématiquement autour de la page 35-37 sur "
                              "~110 possibles, sur deux tentatives séparées — probable limite de "
                              "session côté serveur, pas un bug du collecteur. Pousser au-delà de 40 "
                              "n'a rien changé au résultat final lors des tests (mêmes avis retenus) ; "
                              "à ajuster seulement si le portail change de comportement.")
    parser.add_argument("--maroc-pps-max-documents", type=int, default=30,
                         help="Nombre de documents PPS marocains les plus récents à examiner "
                              "(sur ~5 600+ au total, best-effort, rendement faible — cf. README) ; "
                              "le portail a montré des signes de ralentissement au-delà, à ne pas "
                              "augmenter sans précaution")
    parser.add_argument("--skip-maroc-enrichment", action="store_true",
                         help="Ne pas récupérer montant estimatif/caution par avis PMMP (une requête "
                              "supplémentaire par avis candidat — désactiver pour un run plus rapide)")
    parser.add_argument("--maroc-seuil-montant-mad", type=float, default=1_000_000,
                         help="Exclut les avis PMMP dont le montant estimatif dépasse ce seuil (MAD)")
    parser.add_argument("--from-cache", metavar="FICHIER.json", default=None,
                         help="Ignore toute collecte réseau : relit un cache JSON produit par un échec "
                              "d'écriture précédent (cf. data/cache_non_ecrit_*.json) et l'écrit dans "
                              "l'onglet 'Appels d'offres'. Utile pour rejouer une écriture bloquée par "
                              "Excel sans refaire plusieurs minutes de scraping.")
    args = parser.parse_args()

    if args.from_cache:
        with open(args.from_cache, encoding="utf-8") as f:
            cached_records = json.load(f)
        logger.info("Rejeu depuis le cache %s : %d ligne(s)", args.from_cache, len(cached_records))
        _write_or_cache(excel_writer.write_records, cached_records, "depuis cache")
        return

    if not args.skip_ci:
        logger.info("Collecte DGMP-CI (avis actifs)...")
        try:
            ci_records = collector_ci.collect()
            logger.info("DGMP-CI : %d avis candidats IT avant filtrage", len(ci_records))
            ci_classified = filter_and_classify(ci_records)
            logger.info("DGMP-CI : %d avis après filtrage/classification", len(ci_classified))
            _log_domain_counts("DGMP-CI", ci_classified)
            _write_or_cache(excel_writer.write_records, ci_classified, "DGMP-CI", source="DGMP-CI")
        except collector_ci.CiCollectorError as exc:
            logger.error("Échec collecte DGMP-CI (non bloquant) : %s", exc)

    if not args.skip_maroc:
        logger.info("Collecte PMMP (Maroc, catégorie Services de technologies de l'information)...")
        try:
            ma_records = collector_maroc.collect(max_pages=args.maroc_max_pages)
            logger.info("PMMP : %d avis récupérés avant filtrage", len(ma_records))
            ma_classified = filter_and_classify(ma_records)
            logger.info("PMMP : %d avis après filtrage/classification", len(ma_classified))
            _log_domain_counts("PMMP", ma_classified)

            if not args.skip_maroc_enrichment:
                logger.info(
                    "PMMP : récupération montant estimatif/caution pour %d avis candidats...",
                    len(ma_classified),
                )
                ma_classified = collector_maroc.enrich_records_with_details(ma_classified)
                avant = len(ma_classified)
                ma_classified = [
                    r for r in ma_classified
                    if not is_montant_too_high(r, seuil=args.maroc_seuil_montant_mad)
                ]
                logger.info(
                    "PMMP : %d avis écartés (montant > %.0f MAD), %d restants",
                    avant - len(ma_classified), args.maroc_seuil_montant_mad, len(ma_classified),
                )

            _write_or_cache(excel_writer.write_records, ma_classified, "PMMP", source="PMMP")
        except collector_maroc.MarocCollectorError as exc:
            logger.error("Échec collecte PMMP (non bloquant) : %s", exc)

    if args.include_onda:
        logger.info("Collecte ONDA (Maroc, avis Appels d'offres Achats)...")
        try:
            onda_records = collector_onda.collect()
            logger.info("ONDA : %d avis récupérés avant filtrage", len(onda_records))
            onda_classified = filter_and_classify(onda_records)
            logger.info("ONDA : %d avis après filtrage/classification", len(onda_classified))
            _log_domain_counts("ONDA", onda_classified)

            if not args.skip_maroc_enrichment:
                logger.info(
                    "ONDA : récupération montant estimatif/caution/lien DCE pour %d avis candidats...",
                    len(onda_classified),
                )
                onda_classified = collector_onda.enrich_records_with_details(onda_classified)
                avant = len(onda_classified)
                onda_classified = [
                    r for r in onda_classified
                    if not is_montant_too_high(r, seuil=args.maroc_seuil_montant_mad)
                ]
                logger.info(
                    "ONDA : %d avis écartés (montant > %.0f MAD), %d restants",
                    avant - len(onda_classified), args.maroc_seuil_montant_mad, len(onda_classified),
                )

            _write_or_cache(excel_writer.write_records, onda_classified, "ONDA", source="ONDA")
        except collector_onda.OndaCollectorError as exc:
            logger.error("Échec collecte ONDA (non bloquant) : %s", exc)

    if not args.skip_bceao:
        logger.info("Collecte BCEAO (régional UEMOA, Marchés publics et Achats)...")
        try:
            bceao_records = collector_bceao.collect()
            logger.info("BCEAO : %d avis récupérés avant filtrage", len(bceao_records))
            bceao_classified = filter_and_classify(bceao_records)
            logger.info("BCEAO : %d avis après filtrage/classification", len(bceao_classified))
            _log_domain_counts("BCEAO", bceao_classified)

            if not args.skip_bceao_enrichment:
                logger.info("BCEAO : récupération du lien DCE pour %d avis candidats...", len(bceao_classified))
                bceao_classified = collector_bceao.enrich_records_with_dce(bceao_classified)

            _write_or_cache(excel_writer.write_records, bceao_classified, "BCEAO", source="BCEAO")
        except collector_bceao.BceaoCollectorError as exc:
            logger.error("Échec collecte BCEAO (non bloquant) : %s", exc)

    if not args.skip_bad:
        logger.info("Collecte BAD/AfDB (siège Abidjan, flux projets + corporate)...")
        try:
            bad_records = collector_bad.collect(country_filter=args.bad_country_filter)
            logger.info("BAD : %d avis récupérés avant filtrage", len(bad_records))
            bad_classified = filter_and_classify(bad_records)
            logger.info("BAD : %d avis après filtrage/classification", len(bad_classified))
            _log_domain_counts("BAD", bad_classified)

            if not args.skip_bad_enrichment:
                logger.info("BAD : récupération de la date limite pour %d avis candidats...", len(bad_classified))
                bad_classified = collector_bad.enrich_records_with_deadline(bad_classified)
                avant = len(bad_classified)
                bad_classified = [r for r in bad_classified if not is_deadline_too_soon(r)]
                logger.info(
                    "BAD : %d avis écartés (délai insuffisant une fois la vraie date limite connue), %d restants",
                    avant - len(bad_classified), len(bad_classified),
                )

            _write_or_cache(
                excel_writer.write_records, bad_classified, "BAD",
                source={"BAD (projets)", "BAD (corporate)"},
            )
        except collector_bad.BadCollectorError as exc:
            logger.error("Échec collecte BAD (non bloquant) : %s", exc)

    if not args.skip_maroc_pps:
        logger.info("Collecte PPS (Maroc, programme prévisionnel, best-effort)...")
        try:
            pps_records = collector_maroc_pps.collect(max_documents=args.maroc_pps_max_documents)
            logger.info("PPS Maroc : %d document(s) candidats IT avant classification", len(pps_records))
            pps_classified = []
            for r in pps_records:
                domaine = classify_domain(r)
                if domaine == "hors IT":
                    continue
                pps_classified.append({**r, "domaine": domaine})
            logger.info("PPS Maroc : %d document(s) après classification", len(pps_classified))
            _log_domain_counts("PPS Maroc", pps_classified)
            _write_or_cache(
                excel_writer.write_ppm_records, pps_classified, "PPS Maroc",
                source="PMMP (programme prévisionnel)",
            )
        except collector_maroc_pps.MarocPpsError as exc:
            logger.error("Échec collecte PPS Maroc (non bloquant) : %s", exc)


if __name__ == "__main__":
    main()
