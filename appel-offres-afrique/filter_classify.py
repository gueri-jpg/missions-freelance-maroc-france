"""Filtrage et classification des avis collectés (Côte d'Ivoire / Maroc).

Logique de classification du domaine IT reprise à l'identique de
`APPEL_OFFRES/filter_classify.py` (même définition métier du domaine cible,
indépendante du pays/de la source). Les filtres structurés spécifiques au
BOAMP (accord-cadre, type_procedure, nature_categorise) n'ont pas
d'équivalent fiable dans les sources CI/Maroc collectées ici (pas de CPV, pas
de montant systématique) — seuls le type de marché (fournitures/travaux
purs, hors scope PME de conseil) et la date limite sont utilisés comme
filtres structurés.
"""
from __future__ import annotations

import datetime as dt
import re

import config


def _parse_date(value) -> dt.date | None:
    """Parse une date ISO ou JJ/MM/AAAA en date. Retourne None si non
    parsable — ne jamais exclure sur une donnée qu'on ne sait pas
    interpréter."""
    if not value:
        return None
    s = str(value).strip()
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        pass
    m = re.match(r"^(\d{2})[/-](\d{2})[/-](\d{4})$", s)
    if m:
        day, month, year = m.groups()
        try:
            return dt.date(int(year), int(month), int(day))
        except ValueError:
            return None
    return None


def is_deadline_too_soon(
    record: dict,
    min_days: int = 7,
    date_field: str = "date_limite",
    today: dt.date | None = None,
) -> bool:
    """Exclut un avis dont la date limite de soumission est déjà passée ou
    trop proche (moins de `min_days` jours). Une date absente/non parsable
    n'est JAMAIS un motif d'exclusion (règle d'exactitude)."""
    today = today or dt.date.today()
    deadline = _parse_date(record.get(date_field))
    if deadline is None:
        return False
    return (deadline - today).days < min_days


def is_montant_too_high(record: dict, seuil: float = 1_000_000) -> bool:
    """Exclut un avis dont le montant estimatif (déjà parsé en nombre par le
    collecteur, ex. `montant_estime_valeur` pour le Maroc) dépasse `seuil`
    (1 000 000 MAD par défaut — demandé explicitement, hors cible PME de
    conseil au-delà). Un montant absent/non chiffré N'EST PAS exclu (la
    plupart des sources ne publient pas ce chiffre — règle d'exactitude :
    l'absence d'information n'est jamais un motif d'exclusion silencieuse)."""
    montant = record.get("montant_estime_valeur")
    if montant is None:
        return False
    return montant > seuil


def _contains_keyword(text: str, keywords: list[str]) -> bool:
    """Recherche par MOT ENTIER (limites de mot), pas par sous-chaîne brute.
    Bug réel constaté : le terme d'exclusion BTP "voirie" est une
    sous-chaîne de "ivoirienne"/"ivoirien" — toute annonce mentionnant
    l'administration ou l'État ivoirien se faisait donc exclure à tort par
    un faux signal BTP. `\\b` gère correctement les lettres accentuées
    (Python 3 : Unicode par défaut), donc "ivoirienne" ne contient plus de
    limite de mot avant "voirie".

    Un "s" final optionnel est toléré (pluriel français courant) : sans ça,
    le mot-clé singulier "matériel" ne matchait plus "matériels" une fois
    passé en comparaison par limite de mot stricte — régression constatée
    et corrigée immédiatement (cf. tests)."""
    return any(re.search(rf"\b{re.escape(kw)}s?\b", text) for kw in keywords)


def matches_any_keyword(text: str, keywords: list[str]) -> bool:
    """Version publique de `_contains_keyword`, destinée aux pré-filtres de
    rappel des collecteurs (DGMP-CI, BCEAO, BAD...). Ne JAMAIS réimplémenter
    ce filtrage en sous-chaîne brute (`kw in text`) dans un collecteur —
    bug réel constaté deux fois avec cette approche naïve : "voirie" dans
    "ivoirienne", puis "amo" (ajouté pour couvrir AMO/AMOA/PMO) dans
    "Yamoussoukro" (capitale politique de la Côte d'Ivoire, donc mention
    fréquente dans des avis CI/BCEAO n'ayant aucun rapport avec l'IT)."""
    return _contains_keyword(text, keywords)


_TYPE_SERVICE = {
    "services", "service", "prestations intellectuelles",
    "prestation intellectuelle", "prestations de services",
}


def is_pure_fourniture(record: dict) -> bool:
    """Exclut les marchés de fournitures/travaux purs (type_marche) — hors
    scope pour une PME de conseil. Un type_marche vide/inconnu/de service
    N'EST PAS exclu (l'absence d'information n'est jamais un motif
    d'exclusion silencieuse ; en cas de doute sur la nature exacte, on
    garde).

    Comparaison par préfixe, pas égalité stricte : le PPM Côte d'Ivoire
    utilise des libellés plus détaillés que les catégories brutes DGMP/PMMP
    ("Fourniture informatiques", "Fourniture de véhicule", "Fourniture de
    bureaux"...) — une égalité stricte avec "fourniture" ne matchait aucun
    de ces cas réels et laissait passer des achats de véhicules/consommables
    de bureau classés à tort "à vérifier"/"IT confirmé"."""
    type_marche = (record.get("type_marche") or "").strip().lower()
    if not type_marche:
        return False
    if type_marche in _TYPE_SERVICE:
        return False
    return type_marche.startswith(("fourniture", "travaux"))


def _has_it_keyword(text: str) -> bool:
    """"AMOA"/"maîtrise d'ouvrage" sont des termes génériques utilisés dans
    tous les secteurs — un match sur ces seuls termes ne suffit PAS à
    confirmer le domaine IT. Il faut soit un terme fort, soit un terme
    ambigu combiné à un terme de contexte IT explicite."""
    if _contains_keyword(text, config.MOTS_CLES_IT_FORTS):
        return True
    has_ambigu = _contains_keyword(text, config.MOTS_CLES_AMBIGUS)
    has_contexte = _contains_keyword(text, config.MOTS_CLES_CONTEXTE_IT)
    return has_ambigu and has_contexte


_APOSTROPHE_VARIANTS = str.maketrans({"'": "'", "'": "'", "´": "'", "`": "'"})


def _normalize_apostrophes(text: str) -> str:
    """Uniformise les variantes d'apostrophe vers l'apostrophe ASCII simple
    — les avis utilisent presque systématiquement l'apostrophe typographique
    alors que config.py est écrit avec l'apostrophe simple."""
    return text.translate(_APOSTROPHE_VARIANTS)


def _record_text(record: dict) -> str:
    """Texte utilisé pour la classification — l'OBJET uniquement, jamais le
    nom de l'acheteur. Bug réel constaté : "ACQUISITION DE VEHICULES POUR LA
    SNDI" (Société Nationale de Développement Informatique) était classé
    "IT confirmé" uniquement parce que le nom de l'acheteur contient
    "développement informatique" — l'objet réel (achat de véhicules) n'a
    aucun rapport avec l'IT. Le nom de l'acheteur ne dit rien sur la nature
    de CE marché précis ; seul l'objet doit être analysé (même principe que
    APPEL_OFFRES/filter_classify.py, qui n'a jamais inclus l'acheteur)."""
    objet = record.get("objet") or ""
    return _normalize_apostrophes(objet.lower())


def classify_domain(record: dict) -> str:
    """Classe une ligne en 'IT confirmé' / 'à vérifier' / 'hors IT' à partir
    des mots-clés IT / exclusion BTP-environnement, et des mots d'exclusion
    FORTE (acquisition/fourniture). Ne supprime jamais une ligne — se
    contente de la classer. Logique identique à
    APPEL_OFFRES/filter_classify.classify_domain, sans le signal CPV
    (absent des sources CI/Maroc collectées ici)."""
    text = _record_text(record)

    has_ambigu_amoa = _contains_keyword(text, config.MOTS_CLES_AMBIGUS)

    has_fourniture_service_exception = _contains_keyword(text, config.FOURNITURE_SERVICE_EXCEPTIONS)
    has_fourniture_materielle = (
        _contains_keyword(text, config.MOTS_FOURNITURE) and not has_fourniture_service_exception
    )
    has_acquisition_verbe = _contains_keyword(text, config.MOTS_ACQUISITION) or has_fourniture_materielle
    has_objet_materiel = _contains_keyword(text, config.MOTS_OBJET_MATERIEL)
    has_acquisition_materiel = has_acquisition_verbe and has_objet_materiel

    has_fourniture_forte = _contains_keyword(text, config.MOTS_EXCLUSION_FORTE)
    if not has_ambigu_amoa and (has_acquisition_materiel or has_fourniture_forte):
        return "hors IT"

    has_keyword_it = _has_it_keyword(text)
    has_keyword_exclusion = _contains_keyword(text, config.MOTS_EXCLUSION)

    if has_keyword_it and has_keyword_exclusion:
        return "à vérifier"
    if has_keyword_it:
        return "IT confirmé"
    if has_keyword_exclusion:
        return "hors IT"

    if has_ambigu_amoa:
        return "hors IT"

    # Aucun signal IT ni exclusion détecté : on ne classe jamais "hors IT"
    # sur une simple absence de mot-clé (règle d'exactitude) — la ligne est
    # marquée pour revue manuelle plutôt que silencieusement écartée.
    return "à vérifier"


_DOMAIN_ORDER = {"IT confirmé": 0, "à vérifier": 1, "hors IT": 2}


def filter_and_classify(records: list[dict]) -> list[dict]:
    """Applique le filtre type de marché, la date limite, puis la
    classification de domaine. Ne retourne que les opportunités actives,
    dans le scope IT : les avis classés "hors IT" sont exclus du résultat.
    Triée IT confirmé -> à vérifier."""
    output: list[dict] = []

    for record in records:
        if is_pure_fourniture(record):
            continue
        if is_deadline_too_soon(record, min_days=config.DELAI_MIN_SOUMISSION_JOURS):
            continue

        domaine = classify_domain(record)
        if domaine == "hors IT":
            continue

        enriched = dict(record)
        enriched["domaine"] = domaine
        output.append(enriched)

    output.sort(key=lambda r: _DOMAIN_ORDER.get(r["domaine"], 1))
    return output
