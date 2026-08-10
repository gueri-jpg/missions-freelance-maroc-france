"""Collecte des avis "Appels d'offres Achats" de l'ONDA (Office National Des
Aéroports, Maroc) — https://www.onda.ma.

Source complémentaire au PMMP (collector_maroc.py) : cf. config.py pour le
raisonnement complet (pourquoi ONDA apporte un gain réel alors que ONEE/ANP/
Marsa Maroc/CDG/ADM ont été écartés). Page rendue côté serveur, `requests`
seul suffit (pas de WAF, pas de JS), sans compte requis.

Chaque avis ONDA pointe, sur sa page détail, vers le dossier de consultation
hébergé sur le PMMP (EntrepriseDetailsConsultation) — on réutilise ce lien
pour construire "Lien DCE" (formulaire de demande anonyme, même URL que
collector_maroc.py) plutôt que de pointer vers la page ONDA elle-même.
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import quote, urljoin

import requests

import config

logger = logging.getLogger(__name__)


class OndaCollectorError(Exception):
    """Erreur de communication ou de structure inattendue pour la source ONDA."""


_MOIS_FR = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

# Un bloc <li> de la liste "Appels d'offres Achats" contient le titre complet
# dans un <span> et le lien détail juste après, dans un <a class="suite">.
_ITEM_RE = re.compile(
    r'<li>\s*<h2>\s*<span>(.*?)</span>\s*</h2>.*?<a class="suite" href="([^"]+)"',
    re.DOTALL,
)

# Titre observé en direct, ex. :
#   "N°125/26/AOO/ONDA (publié le 31/07/2026) - Prestations de gardiennage
#    [...] Casablanca Mohammed V - 01 septembre 2026 10:00"
# Formats de référence variables constatés : "N°125/26/AOO/ONDA",
# "N°115-26-AOO" (sans suffixe ONDA), "N° 021/26/AOO/ONDA" (espace après N°).
_TITLE_RE = re.compile(
    r"^(N°\s*\S+)\s*\(publié le (\d{2}/\d{2}/\d{4})\)\s*-\s*(.+?)\s*-\s*"
    r"(\d{1,2}\s+\S+\s+\d{4}\s+\d{2}:\d{2})$"
)

# Constaté en direct : dans le HTML brut (contrairement au DOM déjà résolu
# par un navigateur), l'esperluette d'un attribut href est échappée en
# `&amp;` — `refConsultation=...&amp;orgAcronyme=...`, pas `&` littéral.
_REF_ORG_RE = re.compile(r'refConsultation=([^&"]+?)(?:&amp;|&)orgAcronyme=([^&"]+)')
_TABLE_FIELD_RE = re.compile(r"<th>\s*<p>([^<]+)</p>.*?</th>\s*<td>\s*([^<]*?)\s*</td>", re.DOTALL)


def _clean_date_ddmmyyyy(value: str | None) -> str | None:
    """Normalise 'JJ/MM/AAAA' -> 'AAAA-MM-JJ'. Retourne None si non
    parsable — ne jamais deviner (règle d'exactitude, cf. collector_maroc)."""
    if not value:
        return None
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", value.strip())
    if not m:
        return None
    day, month, year = m.groups()
    return f"{year}-{month}-{day}"


def _parse_date_limite_fr(value: str | None) -> str | None:
    """Parse une date limite au format 'JJ mois AAAA HH:MM' (mois en toutes
    lettres, tel qu'affiché par l'ONDA) -> 'AAAA-MM-JJ'. Retourne None si non
    parsable ou mois non reconnu — ne jamais deviner."""
    if not value:
        return None
    m = re.match(r"^(\d{1,2})\s+(\S+)\s+(\d{4})\s+\d{2}:\d{2}$", value.strip())
    if not m:
        return None
    day, month_name, year = m.groups()
    month = _MOIS_FR.get(month_name.lower())
    if not month:
        return None
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _build_absolute_url(href: str) -> str:
    """Les URL détail ONDA sont des titres complets slugifiés (accents,
    apostrophes, 'N°'...) — encodage requis pour une requête HTTP fiable.
    Constaté en direct : le serveur accepte les apostrophes littérales dans
    le chemin (pas besoin de les encoder)."""
    return urljoin("https://www.onda.ma/", quote(href, safe="/'-.()"))


def fetch_page(url: str = config.MA_ONDA_LISTING_URL) -> str:
    headers = {"User-Agent": config.USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}
    try:
        resp = requests.get(url, headers=headers, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise OndaCollectorError(f"Erreur réseau ONDA : {exc}") from exc
    if not resp.ok:
        raise OndaCollectorError(f"Statut HTTP inattendu ONDA : {resp.status_code}")
    return resp.text


def parse_listing_rows(html: str) -> list[dict]:
    """Extrait les avis bruts de la page listing "Appels d'offres Achats"
    (onglet "En cours" par défaut). Une entrée dont le titre ne correspond
    pas au format attendu est ignorée plutôt que de faire échouer tout le
    lot (best-effort, cf. README pour les cas déjà rencontrés)."""
    rows: list[dict] = []
    for raw_title, href in _ITEM_RE.findall(html):
        title = re.sub(r"\s+", " ", raw_title).strip()
        m = _TITLE_RE.match(title)
        if not m:
            logger.warning("ONDA : titre non reconnu, ignoré : %r", title)
            continue
        reference, date_pub, objet, date_limite = m.groups()
        rows.append({
            "reference": reference.strip(),
            "date_publication": date_pub,
            "objet": objet.strip(),
            "date_limite": date_limite,
            "detail_href": href,
        })
    return rows


def normalize_onda_record(raw: dict) -> dict | None:
    objet = raw.get("objet")
    if not objet:
        return None
    reference = raw.get("reference") or "non précisé"
    detail_href = raw.get("detail_href")
    url_avis = _build_absolute_url(detail_href) if detail_href else config.MA_ONDA_LISTING_URL

    return {
        "id": f"MA-ONDA-{reference}",
        "pays": "Maroc",
        "source": "ONDA",
        "reference": reference,
        "objet": objet,
        "acheteur": "Office National Des Aéroports (ONDA)",
        "type_marche": None,
        "procedure_libelle": None,
        "lieu_execution": None,
        "date_publication": _clean_date_ddmmyyyy(raw.get("date_publication")),
        "date_limite": _parse_date_limite_fr(raw.get("date_limite")),
        "devise": "MAD",
        "montant_estime": None,
        "url_avis": url_avis,
        "lien_dce": None,
    }


def _parse_montant_mad(raw: str | None) -> float | None:
    """Même logique que collector_maroc._parse_montant_mad : format
    marocain ('354 000,00' -> 354000.0), '_' ou '0,00' -> None (placeholder
    de champ vide constaté en direct sur les pages détail ONDA, jamais un
    vrai montant nul)."""
    if not raw:
        return None
    cleaned = raw.strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def fetch_onda_details(url: str) -> dict:
    """Récupère, depuis la page détail ONDA : caution provisoire, estimation
    du coût, et le lien vers le dossier de consultation sur le PMMP (converti
    en formulaire de demande anonyme, même URL que collector_maroc.py).
    Best-effort : retourne {} en cas d'échec réseau, ne bloque jamais
    l'enrichissement du lot pour une seule page défaillante."""
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": config.MA_ONDA_LISTING_URL,
    }
    try:
        resp = requests.get(url, headers=headers, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("ONDA détail %s : erreur réseau (non bloquant) : %s", url, exc)
        return {}
    if not resp.ok:
        return {}

    html = resp.text
    montant = caution = None
    for label, value in _TABLE_FIELD_RE.findall(html):
        label_lower = label.lower()
        if "caution provisoire" in label_lower:
            caution = _parse_montant_mad(value)
        elif "estimation" in label_lower:
            montant = _parse_montant_mad(value)

    lien_dce = None
    m = _REF_ORG_RE.search(html)
    if m:
        ref_consultation, org_acronyme = m.groups()
        lien_dce = (
            f"{config.MA_PMMP_BASE_URL}/index.php"
            f"?page=entreprise.EntrepriseDemandeTelechargementDce"
            f"&refConsultation={ref_consultation}&orgAcronyme={org_acronyme}"
        )

    return {
        "montant_estime": f"{montant:,.2f} MAD".replace(",", " ").replace(".", ",") if montant else None,
        "montant_estime_valeur": montant,
        "caution_provisoire": f"{caution:,.2f} MAD".replace(",", " ").replace(".", ",") if caution else None,
        "lien_dce": lien_dce,
    }


def enrich_records_with_details(records: list[dict]) -> list[dict]:
    """Enrichit chaque avis avec montant/caution/lien DCE — à appeler
    uniquement sur un ensemble déjà filtré/restreint (candidats IT retenus,
    ~14 avis "en cours" au total sur cette source de toute façon)."""
    enriched: list[dict] = []
    for i, record in enumerate(records):
        if i > 0:
            time.sleep(config.REQUEST_DELAY_SECONDS)
        details = fetch_onda_details(record["url_avis"])
        enriched.append({**record, **details})
    return enriched


def collect(url: str = config.MA_ONDA_LISTING_URL) -> list[dict]:
    """Récupère et normalise les avis "Appels d'offres Achats" actuellement
    "en cours" (onglet par défaut de la page) — pas de pagination constatée
    (~14 avis vus en direct, tous tenant sur la page unique)."""
    html = fetch_page(url)
    raw_rows = parse_listing_rows(html)
    logger.info("ONDA : %d ligne(s) brute(s)", len(raw_rows))
    results = []
    for raw in raw_rows:
        normalized = normalize_onda_record(raw)
        if normalized is not None:
            results.append(normalized)
    logger.info("ONDA : %d avis normalisés", len(results))
    return results
