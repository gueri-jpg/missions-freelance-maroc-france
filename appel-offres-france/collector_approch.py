"""Collecte des projets d'achats publics prévisionnels via l'API APProch (DAE).

Source : https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/projets-dachats-publics/records
Ces données sont saisies volontairement par l'acheteur et concernent des
projets NON encore publiés : elles doivent être marquées "estimation
prévisionnelle — à confirmer" et ne remplacent jamais le BOAMP.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)


class ApprochError(Exception):
    """Erreur de communication ou de requête vers l'API APProch."""


SIRENE_API_URL = "https://recherche-entreprises.api.gouv.fr/search"


def resolve_siren_name(siren: str | int, cache: dict[str, str | None] | None = None) -> str | None:
    """Résout un SIREN acheteur en raison sociale via l'API publique
    recherche-entreprises.api.gouv.fr (gouv, sans clé). Best-effort : ne
    lève jamais — retourne None si le SIREN est introuvable ou en cas
    d'erreur réseau, pour ne jamais bloquer la collecte APProch."""
    if not siren:
        return None
    key = str(siren)
    if cache is not None and key in cache:
        return cache[key]

    name: str | None = None
    try:
        resp = requests.get(
            SIRENE_API_URL, params={"q": key}, headers={"User-Agent": config.USER_AGENT},
            timeout=config.HTTP_TIMEOUT,
        )
        if resp.ok:
            results = resp.json().get("results") or []
            if results:
                name = results[0].get("nom_complet")
    except requests.RequestException:
        name = None

    if cache is not None:
        cache[key] = name
    return name


def _build_where_clause(keywords: list[str] | None) -> str | None:
    clauses = ['startswith(code_s_cpv,"72")']
    if keywords:
        kw_clause = " or ".join(f'libelle like "{kw}" or description like "{kw}"' for kw in keywords)
        clauses.append(f"({kw_clause})")
    return " and ".join(clauses)


def fetch_page(where: str | None = None, limit: int = 100, offset: int = 0) -> dict | None:
    """Appelle l'API APProch. Retourne None si le serveur rejette la clause
    `where` (400) — le caller doit alors filtrer côté client."""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if where:
        params["where"] = where
    headers = {"User-Agent": config.USER_AGENT}

    try:
        resp = requests.get(config.APPROCH_API_URL, params=params, headers=headers, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise ApprochError(f"Erreur réseau APProch : {exc}") from exc

    if resp.status_code == 400:
        logger.warning("APProch a renvoyé 400 pour where=%r — repli sur filtrage côté client", where)
        return None
    if not resp.ok:
        raise ApprochError(f"APProch HTTP {resp.status_code} : {resp.text[:300]}")

    return resp.json()


def normalize_approch_record(rec: dict) -> dict:
    """Normalise un enregistrement APProch. Le montant est un texte libre
    saisi par l'acheteur (ex. '40k - 100k€') — jamais reformaté en nombre,
    toujours marqué comme prévisionnel."""
    return {
        "id": f"APPROCH-{rec.get('code')}" if rec.get("code") is not None else None,
        "source": "APProch (prévisionnel)",
        "date_publication": None,
        "date_previsionnelle_publication": rec.get("date_previsionnelle_de_publication"),
        "date_limite": rec.get("date_cible_de_remise_des_offres"),
        "acheteur": None,
        "siren_acheteur": rec.get("siren_de_l_entite_acheteuse"),
        "departement": rec.get("departement_s_d_execution_du_marche"),
        "objet": rec.get("libelle"),
        "description": rec.get("description"),
        "statut": rec.get("statut"),
        "procedure_libelle": rec.get("type_de_procedure"),
        "categorie_achat": rec.get("categorie_d_achat"),
        "cpv": [rec["code_s_cpv"]] if rec.get("code_s_cpv") else [],
        "montant_estime": rec.get("montant_estime_du_marche"),
        "montant_remarque": "estimation prévisionnelle — à confirmer",
        "duree_mois": rec.get("duree_previsionnelle_du_marche"),
        "lien_consultation": rec.get("lien_vers_la_consultation"),
        "url_avis": rec.get("lien_vers_la_consultation"),
        "donnees_raw": rec,
    }


def collect(keywords: list[str] | None = None, max_records: int = 300, page_size: int | None = None) -> list[dict]:
    """Collecte et normalise les projets d'achats IT prévisionnels APProch.
    Non exhaustif par nature (saisie volontaire par l'acheteur)."""
    page_size = page_size or config.APPROCH_PAGE_SIZE
    where = _build_where_clause(keywords)
    fallback_client_filter = False

    results: list[dict] = []
    offset = 0
    siren_cache: dict[str, str | None] = {}

    while len(results) < max_records:
        payload = fetch_page(where=where, limit=page_size, offset=offset)

        if payload is None:
            if where is None:
                raise ApprochError("Requête APProch invalide même sans clause where")
            where = None
            fallback_client_filter = True
            offset = 0
            continue

        records = payload.get("results", [])
        if not records:
            break

        for rec in records:
            if fallback_client_filter:
                cpv = rec.get("code_s_cpv") or ""
                if not cpv.startswith("72"):
                    continue
                if keywords:
                    text = f"{rec.get('libelle') or ''} {rec.get('description') or ''}".lower()
                    if not any(kw.lower() in text for kw in keywords):
                        continue
            results.append(normalize_approch_record(rec))
            if len(results) >= max_records:
                break

        offset += page_size
        if len(records) < page_size:
            break
        time.sleep(config.REQUEST_DELAY_SECONDS)

    results = results[:max_records]
    for record in results:
        record["acheteur"] = resolve_siren_name(record.get("siren_acheteur"), cache=siren_cache)
    return results
