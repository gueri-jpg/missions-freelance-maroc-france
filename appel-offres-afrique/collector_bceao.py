"""Collecte des avis "Marchés publics et Achats" de la BCEAO (Banque
Centrale des États de l'Afrique de l'Ouest) — institution régionale UEMOA.

Cf. config.py pour le raisonnement complet (pourquoi cette page précise et
pas bceao.int/fr/appels-offres, portée régionale et non CI-only). Page rendue
côté serveur, `requests` seul suffit (pas de WAF, pas de JS), sans compte
requis.

Structure Drupal "views" : deux sections sur la même page, "En cours" puis
"Clos" (classe CSS `ttrNow` vs `ttrBefore` sur le <h2> de section) — seule la
section "En cours" est parsée, la coupure se fait avant le <h2> "Clos".
"""
from __future__ import annotations

import html
import logging
import re
import time
from urllib.parse import urljoin

import requests

import config
from filter_classify import matches_any_keyword

logger = logging.getLogger(__name__)


class BceaoCollectorError(Exception):
    """Erreur de communication ou de structure inattendue pour la source BCEAO."""


_APOSTROPHE_VARIANTS = str.maketrans({"'": "'", "‘": "'", "´": "'", "`": "'"})


def _normalize(text: str) -> str:
    return text.translate(_APOSTROPHE_VARIANTS).lower()


def _matches_any_keyword(text: str, keywords: list[str]) -> bool:
    """Pré-filtre de rappel large (même logique que collector_ci.py) —
    INDISPENSABLE ici : contrairement à DGMP-CI (pré-filtré par mots-clés
    côté collecteur) ou au PMMP (pré-filtré par catégorie serveur
    domaineActivite=3.19), la page BCEAO liste TOUS ses avis sans aucun
    filtre de domaine. Sans ce pré-filtre, le filet de sécurité "aucun
    signal -> à vérifier" de classify_domain (pensé pour un flux déjà
    restreint à l'IT) laisse passer en "à vérifier" n'importe quelle
    prestation générique (revêtement, déménagement, traduction...) qui
    n'aurait jamais atteint ce stade sur les sources déjà pré-filtrées —
    constaté en direct, tous les avis BCEAO/BAD initialement collectés
    étaient hors du domaine métier réel de la PME (développement web/
    mobile, BI, AMO/AMOA/PMO IT) sans qu'aucun ne soit une fausse exclusion,
    juste un défaut total de filtrage positif en amont.

    Recherche par mot entier (`filter_classify.matches_any_keyword`), jamais
    par sous-chaîne brute : "amo" (ajouté pour AMO/AMOA/PMO) matchait par
    sous-chaîne à l'intérieur de "Yamoussoukro" — constaté en direct sur un
    avis BCEAO réel (Centre de Traitement Fiduciaire à Yamoussoukro, aucun
    rapport avec l'IT, passait quand même le pré-filtre avant ce correctif)."""
    normalized = _normalize(text)
    return matches_any_keyword(normalized, keywords)


_MOIS_FR = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

_CLOS_HEADING = '<h2 class="ttrBefore">'

# Un item "itemDoc views-row" contient : le lien détail, la date de
# publication, une référence optionnelle suivie de la date limite, puis
# l'objet (span "ttr").
_ITEM_RE = re.compile(
    r'<div class="itemDoc views-row">.*?<a href="([^"]+)">\s*'
    r'<span class="infoFile">\s*[Pp]ubli[ée] le\s*<time[^>]*>([^<]+)</time>\s*</span>\s*'
    r'<span class="descFile"><span class="subTtr">(.*?)Date limite le\s*<time[^>]*>([^<]+)</time>\s*</span>'
    r'<span class="ttr">([^<]*)</span>',
    re.DOTALL,
)

# Les pages détail incluent systématiquement, dans une barre latérale
# partagée par tout le site, des liens PDF vers d'anciens "Rapports sur la
# politique monétaire" (2022-2023) — sans rapport avec l'avis consulté.
# Le vrai document de l'avis (DAO, cahier des charges...) est le seul lien
# PDF restant une fois ce bruit exclu, constaté sur plusieurs pages réelles.
_GENERIC_PDF_MARKER = "olitique"
_PDF_HREF_RE = re.compile(r'href="([^"]+\.pdf[^"]*)"', re.IGNORECASE)


def _clean_reference(value: str | None) -> str | None:
    """Constaté en direct : la référence contient parfois, en plus du code,
    une description complète séparée par ' - ' (ex. 'AC/KO00/APD/010/2026 -
    Fourniture et pose de revêtement sur les murs...') — pas un bug de
    parsing, c'est la donnée source elle-même qui est incohérente d'un avis
    à l'autre. On ne garde que la partie avant ' - ' quand présente : le
    titre réel est de toute façon capturé séparément (span "ttr")."""
    if not value:
        return None
    return value.split(" - ", 1)[0].strip() or None


def _clean_date_fr(value: str | None) -> str | None:
    """Parse une date au format 'JJ mois AAAA' (mois en toutes lettres) ->
    'AAAA-MM-JJ'. Retourne None si non parsable — ne jamais deviner."""
    if not value:
        return None
    m = re.match(r"^(\d{1,2})\s+(\S+)\s+(\d{4})$", value.strip())
    if not m:
        return None
    day, month_name, year = m.groups()
    month = _MOIS_FR.get(month_name.lower())
    if not month:
        return None
    return f"{year}-{int(month):02d}-{int(day):02d}"


def fetch_page(url: str = config.BCEAO_ACHATS_URL) -> str:
    headers = {"User-Agent": config.USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}
    try:
        resp = requests.get(url, headers=headers, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise BceaoCollectorError(f"Erreur réseau BCEAO : {exc}") from exc
    if not resp.ok:
        raise BceaoCollectorError(f"Statut HTTP inattendu BCEAO : {resp.status_code}")
    return resp.text


def parse_listing_rows(page_html: str) -> list[dict]:
    """Extrait les avis bruts de la section "En cours" uniquement — la
    section "Clos" (avis déjà échus) est coupée avant tout parsing."""
    clos_idx = page_html.find(_CLOS_HEADING)
    en_cours_html = page_html[:clos_idx] if clos_idx != -1 else page_html

    rows: list[dict] = []
    for href, date_pub, reference_brute, date_limite, objet in _ITEM_RE.findall(en_cours_html):
        rows.append({
            "detail_href": href,
            "date_publication": html.unescape(date_pub).strip(),
            "reference": _clean_reference(html.unescape(reference_brute)),
            "date_limite": html.unescape(date_limite).strip(),
            "objet": html.unescape(objet).strip(),
        })
    return rows


def normalize_bceao_record(raw: dict) -> dict | None:
    objet = raw.get("objet")
    if not objet:
        return None
    detail_href = raw.get("detail_href")
    url_avis = urljoin(config.BCEAO_ACHATS_URL, detail_href) if detail_href else config.BCEAO_ACHATS_URL
    reference = raw.get("reference") or "non précisé"

    return {
        "id": f"BCEAO-{reference}" if reference != "non précisé" else f"BCEAO-{objet[:40]}",
        "pays": "UEMOA (BCEAO)",
        "source": "BCEAO",
        "reference": reference,
        "objet": objet,
        "acheteur": "BCEAO",
        "type_marche": None,
        "procedure_libelle": None,
        "lieu_execution": None,
        "date_publication": _clean_date_fr(raw.get("date_publication")),
        "date_limite": _clean_date_fr(raw.get("date_limite")),
        "devise": "XOF",
        "montant_estime": None,
        "url_avis": url_avis,
        "lien_dce": None,
    }


def fetch_bceao_dce_link(url: str) -> str | None:
    """Récupère, depuis la page détail, le lien PDF du dossier (DAO/cahier
    des charges) — best-effort, retourne None en cas d'échec réseau ou si
    aucun PDF pertinent n'est trouvé (ne bloque jamais l'enrichissement)."""
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": config.BCEAO_ACHATS_URL,
    }
    try:
        resp = requests.get(url, headers=headers, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("BCEAO détail %s : erreur réseau (non bloquant) : %s", url, exc)
        return None
    if not resp.ok:
        return None

    pdfs = [h for h in _PDF_HREF_RE.findall(resp.text) if _GENERIC_PDF_MARKER not in h]
    if not pdfs:
        return None
    return urljoin(url, pdfs[-1])


def enrich_records_with_dce(records: list[dict]) -> list[dict]:
    """Enrichit chaque avis avec le lien DCE — à appeler uniquement sur un
    ensemble déjà filtré/restreint (candidats IT retenus)."""
    enriched: list[dict] = []
    for i, record in enumerate(records):
        if i > 0:
            time.sleep(config.REQUEST_DELAY_SECONDS)
        lien_dce = fetch_bceao_dce_link(record["url_avis"])
        enriched.append({**record, "lien_dce": lien_dce})
    return enriched


def collect(url: str = config.BCEAO_ACHATS_URL, keywords: list[str] | None = None) -> list[dict]:
    """Récupère et normalise les avis "Marchés publics et Achats" de la
    BCEAO actuellement "En cours", puis ne garde que ceux contenant au moins
    un mot-clé IT (rappel large, cf. `_matches_any_keyword`) — la page ne
    proposant aucun filtre de domaine côté serveur, contrairement à
    DGMP-CI/PMMP."""
    keywords = keywords or config.MOTS_CLES_IT
    page_html = fetch_page(url)
    raw_rows = parse_listing_rows(page_html)
    logger.info("BCEAO : %d ligne(s) brute(s)", len(raw_rows))
    results = []
    for raw in raw_rows:
        normalized = normalize_bceao_record(raw)
        if normalized is None:
            continue
        if not _matches_any_keyword(normalized["objet"], keywords):
            continue
        results.append(normalized)
    logger.info("BCEAO : %d avis candidats IT après filtrage mots-clés", len(results))
    return results
