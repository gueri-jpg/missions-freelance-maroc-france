"""Collecte des Plans de Passation des Marchés (PPM) — Côte d'Ivoire.

Source : https://marchespublics.ci/plan_passation
Équivalent ivoirien d'APProch (France) : programme prévisionnel annuel des
achats publics, publié par trimestre cumulatif au format PDF, structuré en
table (confirmé par extraction réelle : colonnes N° / MINISTERE / AUTORITE
CONTRACTANTE / OBJET DE L'OPERATION / BAILLEUR / LIGNE BUDGETAIRE / TYPE DE
MARCHE / MODE DE PASSATION / DATE DE PUBLICATION).

Ce sont des projets ANNONCÉS par l'acheteur avant publication formelle de
l'avis (donc avant que collector_ci.py puisse les voir) — à traiter comme
"à confirmer", jamais comme un avis ferme. La "DATE DE PUBLICATION" est la
date PRÉVUE de mise en concurrence, pas une échéance de dépôt d'offre :
comme pour APProch, elle n'est jamais utilisée comme critère d'exclusion
(un ministère en retard sur son propre calendrier ne rend pas le projet
caduc), cf. filter_classify.py.
"""
from __future__ import annotations

import datetime as dt
import io
import logging
import re

import pdfplumber
import requests
from lxml import html as lhtml

import config

logger = logging.getLogger(__name__)


class CiPpmError(Exception):
    """Erreur de communication ou de structure inattendue pour la source PPM."""


_APOSTROPHE_VARIANTS = str.maketrans({"'": "'", "'": "'", "´": "'", "`": "'"})


def _normalize(text: str) -> str:
    return text.translate(_APOSTROPHE_VARIANTS).lower()


def _matches_any_keyword(text: str, keywords: list[str]) -> bool:
    normalized = _normalize(text)
    return any(kw in normalized for kw in keywords)


def discover_ppm_pdf_urls(min_year: int) -> list[tuple[str, str]]:
    """Récupère la page /plan_passation et retourne [(libellé, url_pdf)] pour
    les documents "PPM" (Plan de Passation des Marchés, nomenclature actuelle)
    dont le NOM DE FICHIER mentionne une année >= min_year (format 4 chiffres
    "2026" ou 2 chiffres "26" — les deux conventions coexistent dans les noms
    de fichiers réels constatés). Ignore volontairement les PGPM/PGSPM (Plans
    Généraux, nomenclature antérieure à 2020), les PSPM (Plans Simplifiés —
    achats de faible montant standardisés, hors cible PME de conseil), et les
    documents sans année identifiable dans le nom de fichier (souvent des
    plans spécifiques à un projet/bailleur ponctuel, non datés de façon
    fiable — angle mort documenté, cf. README, plutôt que risquer de
    télécharger indistinctement des dizaines de documents non pertinents).

    Le libellé visible (paragraphe voisin du lien "Télécharger") n'est
    utilisé qu'à titre indicatif dans les logs — la structure HTML de cette
    page ne garantit pas une association fiable lien/libellé par simple
    parcours d'ancêtres, seul le nom de fichier est traité comme fiable."""
    headers = {"User-Agent": config.USER_AGENT}
    try:
        resp = requests.get(config.CI_DGMP_PLAN_PASSATION_URL, headers=headers, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise CiPpmError(f"Erreur réseau plan_passation : {exc}") from exc
    if not resp.ok:
        raise CiPpmError(f"plan_passation HTTP {resp.status_code}")
    resp.encoding = resp.apparent_encoding or "utf-8"

    doc = lhtml.fromstring(resp.text)
    candidate_years_4 = {str(y) for y in range(min_year, min_year + 5)}
    candidate_years_2 = {y[-2:] for y in candidate_years_4}
    results: list[tuple[str, str]] = []
    for link in doc.xpath("//a[@href]"):
        href = link.get("href")
        if not href or not re.search(r"\.(pdf|xlsx?)$", href, re.I):
            continue
        filename = href.rsplit("/", 1)[-1].lower()
        if "pgpm" in filename or "pgspm" in filename or "pspm" in filename:
            continue
        if "ppm" not in filename:
            continue
        # Un nom de fichier contenant une année 4 chiffres non ambiguë
        # (ex. "...2023...") est TOUJOURS prioritaire sur le repli 2 chiffres
        # — sinon un jour du mois ("...-27-06-2023...") peut coïncider par
        # hasard avec un millésime candidat et faire garder à tort un
        # document clairement daté d'une année trop ancienne (constaté en
        # direct : a provoqué le téléchargement d'un PPM 2023 non pertinent).
        year4_tokens = re.findall(r"20\d{2}", filename)
        if year4_tokens:
            if not any(tok in candidate_years_4 for tok in year4_tokens):
                continue
        else:
            year2_tokens = re.findall(r"(?<!\d)(\d{2})(?!\d)", filename)
            if not any(tok in candidate_years_2 for tok in year2_tokens):
                continue
        results.append((filename, href))

    return results


def download_pdf(url: str) -> bytes:
    headers = {"User-Agent": config.USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise CiPpmError(f"Erreur réseau téléchargement PPM {url} : {exc}") from exc
    if not resp.ok:
        raise CiPpmError(f"Téléchargement PPM HTTP {resp.status_code} : {url}")
    return resp.content


def parse_ppm_pdf(pdf_bytes: bytes, source_label: str) -> list[dict]:
    """Extrait les lignes de toutes les pages d'un PDF PPM. Ignore
    silencieusement une page sans table détectable (page de garde/sommaire)
    plutôt que d'échouer sur tout le document."""
    rows: list[dict] = []
    header: list[str] | None = None

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                start = 0
                first_row = [(_normalize(c) if c else "") for c in table[0]]
                if any(h.startswith("minist") for h in first_row):
                    header = table[0]
                    start = 1
                if header is None:
                    continue
                for raw_row in table[start:]:
                    if len(raw_row) < len(header):
                        continue
                    record = dict(zip((h or "" for h in header), raw_row))
                    rows.append({k: (v or "").strip() for k, v in record.items() if k})

    logger.info("PPM %s : %d lignes extraites", source_label, len(rows))
    return rows


def _find_col(record: dict, *name_fragments: str) -> str | None:
    for key, value in record.items():
        key_norm = _normalize(key)
        if all(frag in key_norm for frag in name_fragments):
            return value
    return None


def normalize_ppm_record(raw: dict) -> dict | None:
    """Normalise une ligne PPM vers le schéma commun. Retourne None si la
    ligne n'a ni objet ni acheteur exploitable (ligne de rupture/artefact
    d'extraction PDF plutôt qu'une vraie ligne de données)."""
    objet = _find_col(raw, "objet")
    acheteur = _find_col(raw, "autorite", "contractante") or _find_col(raw, "autorit")
    if not objet or not acheteur:
        return None

    ligne_budgetaire = _find_col(raw, "ligne", "budgetaire") or ""
    ref_source = re.sub(r"\s+", "", ligne_budgetaire) or re.sub(r"\W+", "", f"{acheteur}{objet}")[:40]

    return {
        "id": f"CI-PPM-{ref_source}",
        "pays": "Côte d'Ivoire",
        "source": "DGMP-CI (PPM prévisionnel)",
        "reference": ligne_budgetaire or "non précisé",
        "objet": " ".join(objet.split()),
        "acheteur": " ".join(acheteur.split()),
        "ministere": _find_col(raw, "minist"),
        "bailleur": _find_col(raw, "bailleur"),
        "type_marche": _find_col(raw, "type", "march"),
        "mode_passation": _find_col(raw, "mode", "passation"),
        "date_publication": _find_col(raw, "date", "publication"),
        "date_limite": None,  # pas d'échéance ferme — projet prévisionnel
        "devise": "XOF",
        "montant_estime": None,
        "montant_remarque": "estimation prévisionnelle — à confirmer",
        "url_avis": config.CI_DGMP_PLAN_PASSATION_URL,
    }


def collect(keywords: list[str] | None = None, min_year: int | None = None) -> list[dict]:
    """Télécharge et parse les PPM récents, filtre côté client sur mots-clés
    IT (même logique que collector_ci.py), et normalise les projets
    prévisionnels candidats."""
    keywords = keywords or config.MOTS_CLES_IT
    min_year = min_year or (dt.date.today().year - config.CI_PPM_ANNEES_A_COLLECTER + 1)

    pdf_links = discover_ppm_pdf_urls(min_year)
    logger.info("PPM Côte d'Ivoire : %d document(s) trouvé(s) pour l'année >= %d", len(pdf_links), min_year)

    results: list[dict] = []
    seen_ids: set[str] = set()
    for label, href in pdf_links:
        try:
            pdf_bytes = download_pdf(href)
            raw_rows = parse_ppm_pdf(pdf_bytes, label)
        except CiPpmError as exc:
            logger.warning("Échec PPM %s (non bloquant) : %s", label, exc)
            continue

        for raw in raw_rows:
            normalized = normalize_ppm_record(raw)
            if normalized is None:
                continue
            text = f"{normalized['objet']} {normalized['acheteur']}"
            if not _matches_any_keyword(text, keywords):
                continue
            if normalized["id"] in seen_ids:
                continue
            seen_ids.add(normalized["id"])
            results.append(normalized)

    logger.info("PPM Côte d'Ivoire : %d projets candidats IT après filtrage/déduplication", len(results))
    return results
