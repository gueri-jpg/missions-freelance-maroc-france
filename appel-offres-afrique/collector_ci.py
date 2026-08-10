"""Collecte des avis d'appel d'offres publics depuis le site de la Direction
Générale des Marchés Publics de Côte d'Ivoire (DGMP).

Source : https://marchespublics.ci/appel_offre
Page HTML statique (rendue côté serveur, PHP), sans authentification, sans
JavaScript requis — confirmé par récupération directe (~980 lignes, dates de
publication/limite constatées jusqu'en 2026, donc activement tenue à jour).

Distinct de SIGOMAP (sigomap.gouv.ci) : SIGOMAP est le portail transactionnel
(dépôt d'offres) devenu obligatoire depuis le 01/11/2023 pour PARTICIPER à un
marché, mais sa liste d'avis en temps réel n'est visible qu'à un compte
"opérateur économique" connecté (SPA Next.js, backend REST qui répond 403
sans session) — non exploitable par ce collecteur. La page publique de la
DGMP testée ici reste un site distinct, à vocation institutionnelle, qui
publie sa propre liste d'avis sans mur d'authentification.

Aucune API structurée trouvée pour cette source (pas d'équivalent BOAMP) :
seule cette page HTML publique est utilisée. Pas de lien de téléchargement de
dossier de consultation (DAO) constaté sur cette page — probablement
réservé à SIGOMAP après création de compte, cf. LIMITES dans le README.
"""
from __future__ import annotations

import logging

import requests
from lxml import html as lhtml

import config
from filter_classify import matches_any_keyword

logger = logging.getLogger(__name__)


class CiCollectorError(Exception):
    """Erreur de communication ou de structure inattendue pour la source DGMP-CI."""


_APOSTROPHE_VARIANTS = str.maketrans({"'": "'", "'": "'", "´": "'", "`": "'"})


def _normalize(text: str) -> str:
    return text.translate(_APOSTROPHE_VARIANTS).lower()


def _matches_any_keyword(text: str, keywords: list[str]) -> bool:
    """Recherche par mot entier (`filter_classify.matches_any_keyword`), pas
    par sous-chaîne brute. Bug réel constaté en direct : le mot-clé "amo"
    (ajouté pour couvrir AMO/AMOA/PMO) matchait par sous-chaîne à l'intérieur
    de "Yamoussoukro" — n'importe quel avis DGMP-CI mentionnant la capitale
    politique de la Côte d'Ivoire passait donc le pré-filtre à tort."""
    return matches_any_keyword(_normalize(text), keywords)


def fetch_page() -> str:
    """Récupère le HTML brut de la page des avis d'appel d'offres. Un
    User-Agent explicite est envoyé (bonne pratique, cf. README) — le site ne
    publie pas de robots.txt (404 constaté), donc aucune règle explicite à
    respecter au-delà de l'usage raisonnable (délai entre requêtes)."""
    headers = {"User-Agent": config.USER_AGENT}
    try:
        resp = requests.get(
            config.CI_DGMP_APPELS_OFFRES_URL, headers=headers, timeout=config.HTTP_TIMEOUT
        )
    except requests.RequestException as exc:
        raise CiCollectorError(f"Erreur réseau DGMP-CI : {exc}") from exc
    if not resp.ok:
        raise CiCollectorError(f"DGMP-CI HTTP {resp.status_code}")
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def _clean_date(raw: str | None) -> str | None:
    """Nettoie une date brute de la table. La plateforme utilise
    '30-11--0001' comme valeur sentinelle pour une date de publication non
    renseignée — ce n'est pas une vraie date, on ne la garde jamais (règle
    d'exactitude : ne jamais faire passer un sentinel technique pour une
    donnée)."""
    if not raw:
        return None
    raw = raw.strip()
    if not raw or "-0001" in raw or "-1" == raw[-2:]:
        return None
    return raw


def parse_appel_offre_rows(html_text: str) -> list[dict]:
    """Parse la table HTML de la page /appel_offre. Retourne une liste de
    dicts bruts {numero_ao, type_marche, objet, acheteur, date_publication,
    date_limite}. Aucune ligne n'est filtrée à ce stade — c'est le rôle de
    `collect()` puis de filter_classify."""
    doc = lhtml.fromstring(html_text)
    tables = doc.xpath("//table")
    if not tables:
        raise CiCollectorError("Aucune table trouvée sur la page /appel_offre — structure du site modifiée ?")

    rows: list[dict] = []
    for tr in tables[0].xpath(".//tr"):
        cells = tr.xpath("./td")
        if len(cells) < 6:
            continue  # ligne d'en-tête (th) ou ligne incomplète
        texts = [c.text_content().strip() for c in cells]
        numero_ao, type_marche, objet, acheteur, date_pub, date_limite = texts[:6]
        if not numero_ao:
            continue
        rows.append(
            {
                "numero_ao": numero_ao,
                "type_marche": type_marche,
                # Constaté empiriquement : sur les avis anciens (2022-2023),
                # le nom de l'acheteur est concaténé à la fin du champ Objet
                # (la colonne "Autorité Contractante" est alors vide) au lieu
                # d'être dans sa propre colonne comme sur les avis récents.
                # On ne tente PAS de séparer les deux par heuristique (risque
                # d'erreur silencieuse) — l'objet brut est conservé tel quel,
                # et l'acheteur reste "non précisé" dans ce cas.
                "objet": " ".join(objet.split()),
                "acheteur": acheteur if acheteur else None,
                "date_publication": _clean_date(date_pub),
                "date_limite": _clean_date(date_limite),
            }
        )
    return rows


def normalize_ci_record(raw: dict) -> dict:
    """Normalise une ligne DGMP-CI vers le schéma commun utilisé par
    filter_classify / excel_writer (voir README pour le détail des
    colonnes)."""
    return {
        "id": f"CI-{raw['numero_ao']}",
        "pays": "Côte d'Ivoire",
        "source": "DGMP-CI",
        "reference": raw["numero_ao"],
        "objet": raw["objet"],
        "acheteur": raw.get("acheteur") or "non précisé",
        "type_marche": raw.get("type_marche"),
        "date_publication": raw.get("date_publication"),
        "date_limite": raw.get("date_limite"),
        "devise": "XOF",
        "montant_estime": None,
        "url_avis": config.CI_DGMP_APPELS_OFFRES_URL,
    }


def collect(keywords: list[str] | None = None) -> list[dict]:
    """Collecte, filtre côté client sur mots-clés IT (recall large — la
    précision finale est assurée par filter_classify.classify_domain), et
    normalise les avis DGMP-CI.

    Filtrage client obligatoire ici car la page ne propose pas de paramètre
    de recherche côté serveur (contrairement à BOAMP) : sans ce filtre,
    filter_and_classify recevrait l'intégralité des avis tous secteurs
    (travaux, fournitures courantes, etc.), pas seulement les candidats IT."""
    keywords = keywords or config.MOTS_CLES_IT
    html_text = fetch_page()
    raw_rows = parse_appel_offre_rows(html_text)
    logger.info("DGMP-CI : %d lignes brutes récupérées", len(raw_rows))

    results = []
    for raw in raw_rows:
        text = f"{raw['objet']} {raw.get('acheteur') or ''}"
        if not _matches_any_keyword(text, keywords):
            continue
        results.append(normalize_ci_record(raw))

    logger.info("DGMP-CI : %d avis candidats IT après filtrage mots-clés", len(results))
    return results
