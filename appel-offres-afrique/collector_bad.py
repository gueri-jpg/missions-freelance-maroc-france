"""Collecte des avis de la BAD/AfDB (Banque Africaine de Développement),
siège à Abidjan — deux flux RSS distincts, cf. config.py pour le
raisonnement complet (portée panafricaine du flux "Project Procurement",
pourquoi le flux "Corporate Procurement" n'est pas filtré par pays).

Format RSS 2.0 standard, `requests` seul suffit (pas de WAF, pas de JS),
zéro inscription. Les dates limites ne sont disponibles que sur la page
détail de chaque avis (pas dans le flux RSS lui-même) — enrichissement en
aval, uniquement sur les avis candidats retenus après filtrage.
"""
from __future__ import annotations

import html
import logging
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

import config
from filter_classify import matches_any_keyword

logger = logging.getLogger(__name__)


class BadCollectorError(Exception):
    """Erreur de communication ou de structure inattendue pour la source BAD."""


_KEYWORD_APOSTROPHE_VARIANTS = str.maketrans({"'": "'", "‘": "'", "´": "'", "`": "'"})


def _matches_any_keyword(text: str, keywords: list[str]) -> bool:
    """Pré-filtre de rappel large (même logique que collector_ci.py) —
    INDISPENSABLE ici : ni le flux "Project Procurement" (panafricain, tous
    secteurs) ni le flux "Corporate Procurement" (achats internes BAD, tous
    secteurs) ne sont restreints à l'IT côté serveur, contrairement à
    DGMP-CI/PMMP. Sans ce pré-filtre, le filet de sécurité "aucun signal ->
    à vérifier" de classify_domain laisse passer n'importe quelle
    prestation générique (nettoyage, téléphonie, recherche de bureaux...).

    Recherche par mot entier (`filter_classify.matches_any_keyword`), jamais
    par sous-chaîne brute : "amo" (ajouté pour AMO/AMOA/PMO) matchait par
    sous-chaîne à l'intérieur de "Yamoussoukro" — cf. collector_bceao.py où
    ce bug a été constaté en direct sur un avis réel."""
    normalized = text.translate(_KEYWORD_APOSTROPHE_VARIANTS).lower()
    return matches_any_keyword(normalized, keywords)


# Titre structuré du flux "Project Procurement", ex. "AMI - Togo -
# Élaboration de rapports d'achèvement..." — maxsplit=2 tolère les tirets
# supplémentaires à l'intérieur de la description elle-même (ex. "AMI -
# Bénin - Ingénieur Génie Civil - PERU II").
_TITLE_TYPE_COUNTRY_RE = re.compile(r"^([A-Z]{2,4})\s*-\s*([^-]+?)\s*-\s*(.+)$")

_DEADLINE_FIELD_RE = re.compile(
    r'field-name-field-procurement-end-date.*?content="([^"]+)"', re.DOTALL
)


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _normalize_for_match(value: str) -> str:
    return _strip_accents(value).lower().replace("’", "'").replace("‘", "'")


def _matches_country(country: str | None, target: str) -> bool:
    if not country:
        return False
    return _normalize_for_match(target) in _normalize_for_match(country)


def _parse_rfc822_date(value: str | None) -> str | None:
    """Parse une date RFC 822 (format standard des <pubDate> RSS, ex. 'Thu,
    30 Jul 2026 18:17:50 +0000') -> 'AAAA-MM-JJ'. Retourne None si non
    parsable — ne jamais deviner."""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


def _extract_node_id(guid: str | None) -> str | None:
    if not guid:
        return None
    m = re.search(r"(\d+)$", guid.strip())
    return m.group(1) if m else None


def fetch_rss(url: str) -> str:
    headers = {"User-Agent": config.USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}
    try:
        resp = requests.get(url, headers=headers, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise BadCollectorError(f"Erreur réseau BAD ({url}) : {exc}") from exc
    if not resp.ok:
        raise BadCollectorError(f"Statut HTTP inattendu BAD ({url}) : {resp.status_code}")
    return resp.text


def parse_rss_items(xml_text: str) -> list[dict]:
    """Parse un flux RSS 2.0 en liste de dicts bruts. Retourne une liste
    vide si le XML est invalide plutôt que de lever une exception — un flux
    mal formé ne doit jamais interrompre la collecte de l'autre flux."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("BAD : flux RSS invalide, ignoré (%s)", exc)
        return []
    channel = root.find("channel")
    if channel is None:
        return []
    items = []
    for item in channel.findall("item"):
        items.append({
            "title": item.findtext("title"),
            "link": item.findtext("link"),
            "pub_date": item.findtext("pubDate"),
            "guid": item.findtext("guid"),
        })
    return items


def normalize_project_record(raw: dict) -> dict | None:
    """Normalise un avis du flux "Project Procurement". Le titre structuré
    'TYPE - Pays - Description' est décomposé quand reconnu ; sinon le
    titre entier devient l'objet, sans deviner de type/pays (règle
    d'exactitude)."""
    title = html.unescape(raw.get("title") or "").strip()
    if not title:
        return None

    m = _TITLE_TYPE_COUNTRY_RE.match(title)
    if m:
        type_marche, pays_avis, objet = m.group(1), m.group(2).strip(), m.group(3).strip()
    else:
        type_marche, pays_avis, objet = None, None, title

    reference = _extract_node_id(raw.get("guid")) or "non précisé"
    return {
        "id": f"BAD-PROJ-{reference}" if reference != "non précisé" else f"BAD-PROJ-{objet[:40]}",
        "pays": "Afrique (BAD — projets)",
        "source": "BAD (projets)",
        "reference": reference,
        "objet": objet,
        "acheteur": "Banque Africaine de Développement (projet financé)",
        "type_marche": type_marche,
        "procedure_libelle": None,
        "lieu_execution": pays_avis,
        "date_publication": _parse_rfc822_date(raw.get("pub_date")),
        "date_limite": None,
        "devise": None,
        "montant_estime": None,
        "url_avis": raw.get("link"),
        "lien_dce": None,
        "_pays_pour_filtre": pays_avis,
    }


def normalize_corporate_record(raw: dict) -> dict | None:
    """Normalise un avis du flux "Corporate Procurement" (achats internes
    BAD, tous bureaux). Pas de structure TYPE/Pays dans le titre ici."""
    objet = html.unescape(raw.get("title") or "").strip()
    if not objet:
        return None

    reference = _extract_node_id(raw.get("guid")) or "non précisé"
    return {
        "id": f"BAD-CORP-{reference}" if reference != "non précisé" else f"BAD-CORP-{objet[:40]}",
        "pays": "Afrique (BAD — corporate)",
        "source": "BAD (corporate)",
        "reference": reference,
        "objet": objet,
        "acheteur": "Banque Africaine de Développement",
        "type_marche": None,
        "procedure_libelle": None,
        "lieu_execution": None,
        "date_publication": _parse_rfc822_date(raw.get("pub_date")),
        "date_limite": None,
        "devise": None,
        "montant_estime": None,
        "url_avis": raw.get("link"),
        "lien_dce": None,
    }


def fetch_deadline(url: str | None) -> str | None:
    """Récupère la date limite depuis la page détail — best-effort, retourne
    None en cas d'échec réseau ou de champ absent (ne bloque jamais)."""
    if not url:
        return None
    headers = {"User-Agent": config.USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}
    try:
        resp = requests.get(url, headers=headers, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("BAD détail %s : erreur réseau (non bloquant) : %s", url, exc)
        return None
    if not resp.ok:
        return None
    m = _DEADLINE_FIELD_RE.search(resp.text)
    if not m:
        return None
    iso_datetime = m.group(1)
    return iso_datetime[:10] if len(iso_datetime) >= 10 else None


def enrich_records_with_deadline(records: list[dict]) -> list[dict]:
    """Enrichit chaque avis avec sa date limite réelle — à appeler
    uniquement sur un ensemble déjà filtré/restreint (candidats IT retenus)."""
    enriched: list[dict] = []
    for i, record in enumerate(records):
        if i > 0:
            time.sleep(config.REQUEST_DELAY_SECONDS)
        date_limite = fetch_deadline(record.get("url_avis"))
        enriched.append({**record, "date_limite": date_limite})
    return enriched


def collect_project_procurement(
    country_filter: str = "Côte d'Ivoire",
    url: str = config.BAD_PROJECT_PROCUREMENT_RSS_URL,
    keywords: list[str] | None = None,
) -> list[dict]:
    """Flux panafricain, tous secteurs — ne garde que les avis mentionnant
    `country_filter` (comparaison insensible aux accents/apostrophes) ET
    contenant au moins un mot-clé IT (rappel large, aucun filtre de domaine
    côté serveur, contrairement à DGMP-CI/PMMP)."""
    keywords = keywords or config.MOTS_CLES_IT
    xml_text = fetch_rss(url)
    raw_items = parse_rss_items(xml_text)
    logger.info("BAD (projets) : %d avis bruts (toutes zones)", len(raw_items))
    results = []
    for raw in raw_items:
        normalized = normalize_project_record(raw)
        if normalized is None:
            continue
        if not _matches_country(normalized.pop("_pays_pour_filtre", None), country_filter):
            continue
        if not _matches_any_keyword(normalized["objet"], keywords):
            continue
        results.append(normalized)
    logger.info("BAD (projets) : %d avis pour '%s' après filtrage mots-clés", len(results), country_filter)
    return results


def collect_corporate_procurement(
    url: str = config.BAD_CORPORATE_PROCUREMENT_RSS_URL,
    keywords: list[str] | None = None,
) -> list[dict]:
    """Flux des achats internes BAD, tous secteurs — pas de filtre pays (cf.
    config.py), mais même pré-filtre mots-clés IT que le flux projets."""
    keywords = keywords or config.MOTS_CLES_IT
    xml_text = fetch_rss(url)
    raw_items = parse_rss_items(xml_text)
    logger.info("BAD (corporate) : %d avis bruts", len(raw_items))
    results = []
    for raw in raw_items:
        normalized = normalize_corporate_record(raw)
        if normalized is None:
            continue
        if not _matches_any_keyword(normalized["objet"], keywords):
            continue
        results.append(normalized)
    logger.info("BAD (corporate) : %d avis après filtrage mots-clés", len(results))
    return results


def collect(country_filter: str = "Côte d'Ivoire") -> list[dict]:
    """Combine les deux flux BAD. Une erreur sur l'un des deux flux ne doit
    jamais empêcher la collecte de l'autre (best-effort par flux)."""
    results: list[dict] = []
    try:
        results.extend(collect_project_procurement(country_filter=country_filter))
    except BadCollectorError as exc:
        logger.error("Échec collecte BAD (projets), non bloquant : %s", exc)
    try:
        results.extend(collect_corporate_procurement())
    except BadCollectorError as exc:
        logger.error("Échec collecte BAD (corporate), non bloquant : %s", exc)
    return results
