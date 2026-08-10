"""Collecte des avis de marchés publics IT depuis l'API BOAMP (DILA, Licence Ouverte 2.0).

Source : https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records
Doc     : https://www.data.gouv.fr/datasets/boamp

Le champ "donnees" contient un JSON dont la structure dépend du schéma source :
- avis récents (eForms) : clés préfixées cac:/cbc:/efac: (ex. cbc:ItemClassificationCode)
- avis plus anciens (XSD Boamp_v2xx) : clés en clair (ex. OBJET.CPV.PRINCIPAL)
`find_by_key_suffix` recherche récursivement par nom de clé local (après un
éventuel préfixe "xxx:"), ce qui rend l'extraction robuste aux deux schémas
sans avoir à les distinguer explicitement.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)


class BoampError(Exception):
    """Erreur de communication ou de requête vers l'API BOAMP."""


# ---------------------------------------------------------------------------
# Extraction robuste depuis le champ "donnees" (best-effort)
# ---------------------------------------------------------------------------

def _local_name(key: Any) -> Any:
    """Retire un éventuel préfixe de namespace : 'cbc:ID' -> 'ID'."""
    if isinstance(key, str) and ":" in key:
        return key.rsplit(":", 1)[-1]
    return key


def find_by_key_suffix(data: Any, target: str, list_name: str | None = None) -> list[Any]:
    """Recherche récursive, dans un JSON imbriqué (dict/list), de toutes les
    valeurs dont la clé porteuse a pour nom local `target` (comparaison
    insensible à la casse, préfixe cac:/cbc:/efac: ignoré).

    Si `list_name` est fourni, ne conserve que les valeurs qui sont des dict
    avec "@listName" == list_name (utile pour distinguer plusieurs
    ItemClassificationCode eForms selon la liste de codes visée, ex. "cpv").
    """
    results: list[Any] = []
    target_lower = target.lower()

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(_local_name(k), str) and _local_name(k).lower() == target_lower:
                    if list_name is None or (isinstance(v, dict) and v.get("@listName") == list_name):
                        results.append(v)
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(data)
    return results


def _text_value(v: Any) -> str | None:
    """Extrait une valeur texte d'un noeud JSON eForms ({'#text': ...}) ou
    d'une simple chaîne (ancien schéma / eForms sans attribut)."""
    if isinstance(v, str):
        return v or None
    if isinstance(v, dict):
        text = v.get("#text")
        if isinstance(text, str):
            return text or None
    return None


_MONTANT_KEYS = (
    "EstimatedOverallContractAmount",  # eForms — montant estimé (avis de marché)
    "TotalAmount",                     # eForms — montant total (résultat de marché)
    "PayableAmount",                   # eForms — montant du marché attribué
)


def extract_cpv_codes(donnees: dict) -> list[str]:
    """CPV — eForms: cbc:ItemClassificationCode[@listName=cpv]. Ancien schéma:
    OBJET.CPV.PRINCIPAL (dict ou liste de dicts)."""
    codes: set[str] = set()

    for v in find_by_key_suffix(donnees, "ItemClassificationCode", list_name="cpv"):
        t = _text_value(v)
        if t:
            codes.add(t)

    for v in find_by_key_suffix(donnees, "CPV"):
        candidates = v.get("PRINCIPAL") if isinstance(v, dict) else None
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and isinstance(item.get("PRINCIPAL"), str):
                    codes.add(item["PRINCIPAL"])
        elif isinstance(candidates, str):
            codes.add(candidates)
        elif isinstance(candidates, list):
            codes.update(c for c in candidates if isinstance(c, str))

    return sorted(codes)


def extract_montant(donnees: dict) -> tuple[str | None, str | None]:
    """Montant estimé best-effort. Retourne (montant, devise) ou (None, None)
    si absent — ne JAMAIS inventer de valeur."""
    for key in _MONTANT_KEYS:
        for v in find_by_key_suffix(donnees, key):
            t = _text_value(v)
            if t:
                devise = v.get("@currencyID") if isinstance(v, dict) else None
                return t, devise

    # Ancien schéma : ACCORD_CADRE.VALEUR ou CARACTERISTIQUES.VALEUR
    for v in find_by_key_suffix(donnees, "VALEUR"):
        t = _text_value(v)
        if t:
            devise = v.get("@DEVISE") if isinstance(v, dict) else None
            return t, devise

    return None, None


def extract_duree(donnees: dict) -> str | None:
    """Durée du marché, best-effort, tous schémas confondus. MAPA : nbMois.
    Ancien schéma : DUREE_MOIS. eForms : DurationMeasure (+ @unitCode)."""
    for v in find_by_key_suffix(donnees, "nbMois"):
        t = _text_value(v)
        if t:
            return f"{t} mois"

    for v in find_by_key_suffix(donnees, "DUREE_MOIS"):
        t = _text_value(v)
        if t:
            return f"{t} mois"

    for v in find_by_key_suffix(donnees, "DurationMeasure"):
        t = _text_value(v)
        if t:
            unit = v.get("@unitCode") if isinstance(v, dict) else None
            if unit:
                return f"{t} {unit.lower()}"
            return t

    return None


def is_accord_cadre(donnees: dict) -> bool:
    """Détecte un accord-cadre. Ancien schéma : présence de la clé
    ACCORD_CADRE (flag ou objet). eForms : ContractingSystemTypeCode
    [@listName=framework-agreement] != 'none'."""
    if find_by_key_suffix(donnees, "ACCORD_CADRE"):
        return True

    for v in find_by_key_suffix(donnees, "ContractingSystemTypeCode", list_name="framework-agreement"):
        t = _text_value(v)
        if t and t != "none":
            return True

    return False


def extract_buyer_profile_url(donnees: dict) -> str | None:
    """Lien profil acheteur / DCE. eForms: cbc:BuyerProfileURI. Ancien schéma:
    IDENTITE.URL_PROFIL_ACHETEUR."""
    # "urlProfilAcheteur" (schéma MAPA — procédures adaptées, confirmé sur
    # données réelles) ; "BuyerProfileURI" (eForms) ; "URL_PROFIL_ACHETEUR"
    # (ancien schéma XSD).
    for key in ("urlProfilAcheteur", "BuyerProfileURI", "URL_PROFIL_ACHETEUR"):
        for v in find_by_key_suffix(donnees, key):
            t = _text_value(v)
            if t:
                return t
    return None


def extract_criteres_attribution(donnees: dict) -> str | None:
    """Grille de notation / critères d'attribution, texte libre best-effort.
    Ancien schéma : CRITERES_LIBRE (texte) ou CRITERE (liste pondérée avec
    attribut @POIDS). Schéma MAPA (procédures adaptées, confirmé sur données
    réelles) : criterePondere, liste de {critere, criterePCT}."""
    parts: list[str] = []

    for v in find_by_key_suffix(donnees, "CRITERES_LIBRE"):
        t = _text_value(v)
        if t:
            parts.append(t)

    criteres = find_by_key_suffix(donnees, "CRITERE")
    for v in criteres:
        items = v if isinstance(v, list) else [v]
        for item in items:
            if isinstance(item, dict):
                txt = item.get("#text")
                poids = item.get("@POIDS")
                if txt:
                    parts.append(f"{txt} ({poids}%)" if poids else txt)

    for v in find_by_key_suffix(donnees, "criterePondere"):
        items = v if isinstance(v, list) else [v]
        for item in items:
            if isinstance(item, dict):
                txt = item.get("critere")
                poids = item.get("criterePCT")
                if txt:
                    parts.append(f"{txt} ({poids}%)" if poids else txt)

    return " ; ".join(parts) if parts else None


def normalize_boamp_record(rec: dict) -> dict:
    """Normalise un enregistrement brut de l'API BOAMP en dict exploitable
    par filter_classify / excel_writer. Les champs absents restent None —
    aucune valeur n'est inventée (règle d'exactitude)."""
    donnees_raw = rec.get("donnees")
    donnees: dict = {}
    if donnees_raw:
        try:
            donnees = json.loads(donnees_raw) if isinstance(donnees_raw, str) else donnees_raw
        except (json.JSONDecodeError, TypeError):
            logger.warning("Champ 'donnees' illisible pour idweb=%s", rec.get("idweb"))
            donnees = {}

    montant, devise = extract_montant(donnees)
    departement = rec.get("code_departement")
    if isinstance(departement, list):
        departement = ", ".join(departement)

    return {
        "id": rec.get("idweb") or rec.get("id"),
        "source": "BOAMP",
        "date_publication": rec.get("dateparution"),
        "date_limite": rec.get("datelimitereponse"),
        "acheteur": rec.get("nomacheteur"),
        "departement": departement,
        "objet": rec.get("objet"),
        "procedure_libelle": rec.get("procedure_libelle"),
        "type_procedure": rec.get("type_procedure"),
        "procedure_categorise": rec.get("procedure_categorise"),
        "type_marche": rec.get("type_marche"),
        "nature_categorise": rec.get("nature_categorise"),
        "nature_categorise_libelle": rec.get("nature_categorise_libelle"),
        "descripteur_libelle": rec.get("descripteur_libelle"),
        "cpv": extract_cpv_codes(donnees),
        "montant_estime": montant,
        "devise": devise,
        "accord_cadre": is_accord_cadre(donnees),
        "lien_profil_acheteur": extract_buyer_profile_url(donnees),
        "criteres_attribution": extract_criteres_attribution(donnees),
        "duree": extract_duree(donnees),
        "url_avis": rec.get("url_avis"),
        "donnees_raw": donnees,
    }


# ---------------------------------------------------------------------------
# Appels API
# ---------------------------------------------------------------------------

def _build_where_clause(keywords: list[str] | None, adaptee_only: bool) -> str | None:
    clauses = []
    if keywords:
        kw_clause = " or ".join(f'objet like "{kw}"' for kw in keywords)
        clauses.append(f"({kw_clause})")
    if adaptee_only:
        clauses.append('type_procedure="PROCEDURE_ADAPTE"')
    return " and ".join(clauses) if clauses else None


def fetch_page(
    where: str | None = None,
    limit: int = 100,
    offset: int = 0,
    order_by: str = "dateparution desc",
) -> dict | None:
    """Appelle l'API BOAMP pour une page de résultats. Retourne None si le
    serveur rejette la clause `where` (400) — le caller doit alors filtrer
    côté client."""
    params: dict[str, Any] = {"limit": limit, "offset": offset, "order_by": order_by}
    if where:
        params["where"] = where
    headers = {"User-Agent": config.USER_AGENT}

    try:
        resp = requests.get(config.BOAMP_API_URL, params=params, headers=headers, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise BoampError(f"Erreur réseau BOAMP : {exc}") from exc

    if resp.status_code == 400:
        logger.warning("BOAMP a renvoyé 400 pour where=%r — repli sur filtrage côté client", where)
        return None
    if not resp.ok:
        raise BoampError(f"BOAMP HTTP {resp.status_code} : {resp.text[:300]}")

    return resp.json()


def collect(
    keywords: list[str] | None = None,
    adaptee_only: bool = False,
    max_records: int = 500,
    page_size: int | None = None,
) -> list[dict]:
    """Collecte et normalise les avis BOAMP correspondant aux mots-clés IT.

    Tente d'abord un filtrage côté serveur (ODSQL `where`). Si l'API renvoie
    400 (syntaxe refusée), retente sans `where` et filtre les mots-clés côté
    client sur le champ `objet` (best-effort, cf. limites documentées)."""
    page_size = page_size or config.BOAMP_PAGE_SIZE
    where = _build_where_clause(keywords, adaptee_only)
    fallback_client_filter = False

    results: list[dict] = []
    offset = 0

    while len(results) < max_records:
        payload = fetch_page(where=where, limit=page_size, offset=offset)

        if payload is None:
            if where is None:
                raise BoampError("Requête BOAMP invalide même sans clause where")
            where = None
            fallback_client_filter = True
            offset = 0
            continue

        records = payload.get("results", [])
        if not records:
            break

        for rec in records:
            normalized = normalize_boamp_record(rec)
            if fallback_client_filter:
                objet = (normalized.get("objet") or "").lower()
                if keywords and not any(kw.lower() in objet for kw in keywords):
                    continue
                if adaptee_only and normalized.get("type_procedure") != "PROCEDURE_ADAPTE":
                    continue
            results.append(normalized)
            if len(results) >= max_records:
                break

        offset += page_size
        if len(records) < page_size:
            break
        time.sleep(config.REQUEST_DELAY_SECONDS)

    return results[:max_records]


def discover_fields(limit: int = 1) -> dict:
    """Interroge l'API avec records?limit=N et retourne le JSON brut, pour la
    découverte de schéma en réel (section 1 du cahier des charges)."""
    payload = fetch_page(limit=limit, order_by="dateparution desc")
    if payload is None:
        raise BoampError("Impossible de découvrir les champs BOAMP")
    return payload


def list_all_keys(obj: Any, prefix: str = "") -> list[str]:
    """Liste triée de tous les chemins de clés trouvés dans un JSON imbriqué —
    utilitaire de log pour la découverte de schéma."""
    keys: set[str] = set()

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                keys.add(f"{path}{k}")
                _walk(v, f"{path}{k}.")
        elif isinstance(node, list):
            for item in node:
                _walk(item, path)

    _walk(obj, prefix)
    return sorted(keys)
