"""Filtrage et classification des avis collectés (BOAMP / APProch).

Trois responsabilités distinctes, appliquées dans cet ordre par
`filter_and_classify` :
1. Exclusion des accords-cadres dont le montant connu dépasse le seuil PME.
2. Filtrage de la procédure (--adaptee) — les procédures inconnues/NC ne sont
   JAMAIS exclues, seulement marquées "procédure à vérifier".
3. Classification du domaine IT : "IT confirmé" / "à vérifier" / "hors IT".
   Aucune ligne n'est supprimée sur ce seul critère — le classement sert de
   filtre pour le téléchargement des DCE (downloader.py), pas de suppression
   de données.
"""
from __future__ import annotations

import datetime as dt
import re

import config


def _parse_date(value) -> dt.date | None:
    """Parse une date/datetime ISO 8601 (avec ou sans heure/fuseau) en
    date. Retourne None si non parsable — ne jamais exclure sur une donnée
    qu'on ne sait pas interpréter."""
    if not value:
        return None
    s = str(value).strip()
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def is_deadline_passed(record: dict, date_field: str = "date_limite", today: dt.date | None = None) -> bool:
    """Exclut un avis dont la date limite (`date_field`) est déjà passée —
    l'opportunité n'est plus active. Une date absente/non parsable n'est
    JAMAIS un motif d'exclusion (règle d'exactitude)."""
    today = today or dt.date.today()
    deadline = _parse_date(record.get(date_field))
    if deadline is None:
        return False
    return deadline < today


def is_deadline_too_soon(
    record: dict,
    min_days: int = 7,
    date_field: str = "date_limite",
    today: dt.date | None = None,
) -> bool:
    """Exclut un avis dont la date limite de soumission est déjà passée OU
    trop proche (moins de `min_days` jours) pour permettre à une PME de
    conseil de constituer une réponse dans les temps. Englobe
    `is_deadline_passed` (une date passée a un nombre de jours restants
    négatif, donc toujours < min_days). Une date absente/non parsable n'est
    JAMAIS un motif d'exclusion (règle d'exactitude)."""
    today = today or dt.date.today()
    deadline = _parse_date(record.get(date_field))
    if deadline is None:
        return False
    return (deadline - today).days < min_days


def is_date_too_old(
    record: dict,
    date_field: str,
    max_age_days: int = 20,
    today: dt.date | None = None,
) -> bool:
    """Exclut un projet dont la date (`date_field`) est passée depuis plus de
    `max_age_days` jours. Contrairement à `is_deadline_passed`, une date
    récemment passée (ex. une date prévisionnelle de publication APProch
    dépassée depuis quelques jours seulement — le projet a pu depuis être
    formellement publié) reste conservée. Les dates futures ne sont jamais
    exclues. Une date absente/non parsable n'est jamais un motif
    d'exclusion."""
    today = today or dt.date.today()
    date_value = _parse_date(record.get(date_field))
    if date_value is None:
        return False
    if date_value >= today:
        return False
    return (today - date_value).days > max_age_days


def _parse_montant(value) -> float | None:
    """Convertit un montant texte (ex. '9 700 000', '140000.00', '120 000€')
    en float. Retourne None si non parsable — ne jamais deviner."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[€$\s]", "", str(value).strip())
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def is_accord_cadre_excluded(record: dict, seuil: float | None = None) -> bool:
    """Exclut un accord-cadre dont le montant/plafond connu dépasse `seuil`
    (PME de conseil, cible < 100k€ HT). Un accord-cadre sans montant connu
    est conservé — l'absence d'information n'est jamais un motif d'exclusion
    silencieuse."""
    if seuil is None:
        seuil = config.SEUIL_ACCORD_CADRE
    if not record.get("accord_cadre"):
        return False
    montant = _parse_montant(record.get("montant_estime"))
    if montant is None:
        return False
    return montant > seuil


def is_avis_non_appel_offre(record: dict) -> bool:
    """Exclut les avis BOAMP qui ne sont PAS un appel à la concurrence actif
    (`nature_categorise` hors famille "appeloffre/*") : avis d'attribution
    ("résultats de marché" — le marché est déjà attribué), rectificatifs,
    modifications, informations, intentions de conclure, annulations, etc.
    Constaté sur l'API : la famille "attribution/*" représente à elle seule
    ~28 % de l'ensemble du dataset BOAMP — sans ce filtre, des marchés déjà
    clos/attribués se retrouvaient mélangés aux appels d'offres actifs.
    Une nature absente/non reconnue N'EST PAS exclue (règle d'exactitude) :
    seule une valeur explicitement hors de la famille "appeloffre" exclut."""
    nature = (record.get("nature_categorise") or "").strip().lower()
    if not nature:
        return False
    return not nature.startswith("appeloffre")


def is_pure_fourniture(record: dict) -> bool:
    """Exclut les marchés de fournitures/travaux purs (type_marche BOAMP) —
    hors scope pour une PME de conseil (vente de prestations de service, pas
    de matériel/licences). Un type_marche vide/inconnu N'EST PAS exclu :
    l'absence d'information n'est jamais un motif d'exclusion silencieuse."""
    type_marche = record.get("type_marche") or []
    if not type_marche:
        return False
    has_services = "SERVICES" in type_marche
    has_fourniture_ou_travaux = any(t in ("FOURNITURES", "TRAVAUX") for t in type_marche)
    return has_fourniture_ou_travaux and not has_services


def check_procedure(record: dict, adaptee_only: bool) -> tuple[bool, str]:
    """Retourne (garder, statut_procedure).

    Si le champ procédure est vide ou "Procédure NC", la ligne n'est JAMAIS
    exclue par --adaptee : elle est conservée et marquée "procédure à
    vérifier" pour revue manuelle."""
    type_procedure = record.get("type_procedure")
    procedure_libelle = (record.get("procedure_libelle") or "").strip()

    if not type_procedure or procedure_libelle in ("", "Procédure NC"):
        return True, "procédure à vérifier"

    if type_procedure == "PROCEDURE_ADAPTE":
        return True, procedure_libelle or "Procédure Adaptée"

    if adaptee_only:
        return False, procedure_libelle

    return True, procedure_libelle


def _has_it_keyword(text: str) -> bool:
    """"AMOA"/"maîtrise d'ouvrage" sont des termes génériques utilisés dans
    tous les secteurs (BTP, environnement, assurance...) — un match sur ces
    seuls termes ne suffit PAS à confirmer le domaine IT. Il faut soit un
    terme fort (sans ambiguïté sectorielle), soit un terme ambigu combiné à
    un terme de contexte IT explicite (ex. "AMOA" + "système d'information")."""
    if any(kw in text for kw in config.MOTS_CLES_IT_FORTS):
        return True
    has_ambigu = any(kw in text for kw in config.MOTS_CLES_AMBIGUS)
    has_contexte = any(kw in text for kw in config.MOTS_CLES_CONTEXTE_IT)
    return has_ambigu and has_contexte


_APOSTROPHE_VARIANTS = str.maketrans({"’": "'", "‘": "'", "´": "'", "`": "'"})


def _normalize_apostrophes(text: str) -> str:
    """Uniformise les variantes d'apostrophe (typographique '’', accent
    aigu...) vers l'apostrophe ASCII simple. Constaté empiriquement : les
    avis BOAMP utilisent presque systématiquement l'apostrophe typographique
    ('maîtrise d’ouvrage'), alors que les listes de mots-clés de config.py
    sont écrites avec l'apostrophe simple ('maîtrise d'ouvrage') — sans cette
    normalisation, la quasi-totalité des correspondances sur des expressions
    avec apostrophe (maîtrise d'ouvrage, système d'information...) échouent
    silencieusement."""
    return text.translate(_APOSTROPHE_VARIANTS)


def _record_text(record: dict) -> str:
    """Construit le texte d'analyse d'un avis à partir de tous les champs
    textuels disponibles (BOAMP : objet + descripteur_libelle ; APProch :
    objet + description)."""
    objet = record.get("objet") or ""
    descripteur = record.get("descripteur_libelle") or []
    descripteur_text = " ".join(descripteur) if isinstance(descripteur, list) else str(descripteur)
    description = record.get("description") or ""
    return _normalize_apostrophes(f"{objet} {descripteur_text} {description}".lower())


def classify_domain(record: dict) -> str:
    """Classe une ligne en 'IT confirmé' / 'à vérifier' / 'hors IT' à partir
    du CPV (signal fort), des mots-clés IT / exclusion BTP-environnement
    (signal faible), et des mots d'exclusion FORTE (acquisition/fourniture —
    dominent, cf. objectif métier : hors scope maintenance, acquisition,
    fournitures). Ne supprime jamais une ligne — se contente de la classer."""
    text = _record_text(record)

    # Exclusion forte : décrit la nature du marché (achat direct de
    # matériel/licences), pas son sujet — domine même en présence d'un
    # mot-clé IT fort (ex. "Acquisition de licences Business Intelligence"
    # reste hors scope). Détection par CO-OCCURRENCE (verbe d'acquisition +
    # objet matériel/logiciel, indépendamment de l'ordre/proximité) plutôt
    # que par phrase exacte, pour couvrir les formulations réelles variées
    # ("Acquisition, hébergement et maintenance d'un logiciel..."). EXCEPTION :
    # une mission d'AMOA/assistance à maîtrise d'ouvrage reste une prestation
    # de service même si son objet porte sur une acquisition (ex. "AMOA pour
    # l'acquisition d'un logiciel") — dans ce cas on laisse la logique
    # normale trancher plutôt que d'exclure aveuglément une mission de conseil.
    has_ambigu_amoa = any(kw in text for kw in config.MOTS_CLES_AMBIGUS)

    has_fourniture_service_exception = any(kw in text for kw in config.FOURNITURE_SERVICE_EXCEPTIONS)
    has_fourniture_materielle = (
        any(kw in text for kw in config.MOTS_FOURNITURE) and not has_fourniture_service_exception
    )
    has_acquisition_verbe = any(kw in text for kw in config.MOTS_ACQUISITION) or has_fourniture_materielle
    has_objet_materiel = any(kw in text for kw in config.MOTS_OBJET_MATERIEL)
    has_acquisition_materiel = has_acquisition_verbe and has_objet_materiel

    has_fourniture_forte = any(kw in text for kw in config.MOTS_EXCLUSION_FORTE)
    if not has_ambigu_amoa and (has_acquisition_materiel or has_fourniture_forte):
        return "hors IT"

    cpv_codes = record.get("cpv") or []
    has_cpv_it = any(c.startswith(config.CPV_PREFIXES_CIBLES) for c in cpv_codes)
    has_cpv_excluded = any(c.startswith(config.CPV_PREFIXES_EXCLUS) for c in cpv_codes)

    has_keyword_it = _has_it_keyword(text)
    has_keyword_exclusion = any(kw in text for kw in config.MOTS_EXCLUSION)

    if has_cpv_it and has_cpv_excluded:
        return "à vérifier"

    if has_cpv_it:
        return "à vérifier" if (has_keyword_exclusion and not has_keyword_it) else "IT confirmé"

    if has_cpv_excluded:
        return "à vérifier" if has_keyword_it else "hors IT"

    if has_keyword_it and has_keyword_exclusion:
        return "à vérifier"
    if has_keyword_it:
        return "IT confirmé"
    if has_keyword_exclusion:
        return "hors IT"

    # Un terme ambigu (AMOA/maîtrise d'ouvrage) sans AUCUN signal IT (ni CPV
    # 72, ni mot-clé fort, ni contexte IT) décrit très majoritairement une
    # mission hors informatique (urbanisme, assurance, énergie, déchets, RH,
    # juridique, DSP...) — AMOA est un métier transversal utilisé dans tous
    # les secteurs de l'action publique, pas un signal IT en soi. Constaté
    # empiriquement : sur un lot réel d'avis "à vérifier" laissés par
    # l'ancien comportement (défaut "à vérifier"), 52/54 étaient de l'AMOA
    # générique sans aucun rapport avec l'IT ; les 2 seuls avis pertinents
    # avaient un vrai contexte IT (donc déjà couverts par les branches
    # ci-dessus, pas par celle-ci).
    if has_ambigu_amoa:
        return "hors IT"

    return "à vérifier"


_DOMAIN_ORDER = {"IT confirmé": 0, "à vérifier": 1, "hors IT": 2}


def filter_and_classify(
    records: list[dict],
    adaptee_only: bool = False,
    seuil_accord_cadre: float | None = None,
) -> list[dict]:
    """Applique l'exclusion accord-cadre, le filtre procédure, l'exclusion
    des avis hors appel-à-la-concurrence (attribution/rectificatif/etc.) puis
    la classification de domaine. Ne retourne que les opportunités actives,
    avec au moins `config.DELAI_MIN_SOUMISSION_JOURS` avant la date limite de
    soumission, et dans le scope IT : les avis classés "hors IT" sont exclus
    du résultat (ils ne sont plus jamais écrits dans l'Excel). Triée IT
    confirmé -> à vérifier."""
    output: list[dict] = []

    for record in records:
        if is_accord_cadre_excluded(record, seuil_accord_cadre):
            continue
        if is_pure_fourniture(record):
            continue
        if is_deadline_too_soon(record, min_days=config.DELAI_MIN_SOUMISSION_JOURS):
            continue
        if is_avis_non_appel_offre(record):
            continue

        garder_procedure, statut_procedure = check_procedure(record, adaptee_only)
        if not garder_procedure:
            continue

        domaine = classify_domain(record)
        if domaine == "hors IT":
            continue

        enriched = dict(record)
        enriched["domaine"] = domaine
        enriched["statut_procedure"] = statut_procedure
        output.append(enriched)

    output.sort(key=lambda r: _DOMAIN_ORDER.get(r["domaine"], 1))
    return output


# ---------------------------------------------------------------------------
# APProch — mêmes filtres que BOAMP (domaine, montant), adaptés aux champs
# spécifiques à cette source (plage de montant textuelle, catégorie d'achat
# au lieu de type_marche, pas d'accord-cadre ni de procédure fiable).
# ---------------------------------------------------------------------------

_UNIT_MULTIPLIERS = {"k": 1_000, "m": 1_000_000}


def _parse_montant_token(token: str) -> float | None:
    token = token.strip().lower().replace("€", "").replace(",", ".").strip()
    if not token:
        return None
    mult = 1
    if token[-1] in _UNIT_MULTIPLIERS:
        mult = _UNIT_MULTIPLIERS[token[-1]]
        token = token[:-1].strip()
    try:
        return float(token) * mult
    except ValueError:
        return None


def parse_montant_range_approch(value) -> tuple[float | None, float | None]:
    """Parse une plage de montant textuelle APProch (ex. '40k - 100k€',
    '100k - 500k€', '+ 100M€') en (min, max). Retourne (None, None) si non
    parsable — ne jamais deviner une valeur absente."""
    if not value:
        return None, None
    s = str(value).strip()
    if s.startswith("+") or s.startswith(">"):
        return _parse_montant_token(s[1:]), None
    if s.startswith("<"):
        return None, _parse_montant_token(s[1:])
    if "-" in s:
        left, _, right = s.partition("-")
        return _parse_montant_token(left), _parse_montant_token(right)
    single = _parse_montant_token(s)
    return single, single


def is_montant_approch_hors_cible(record: dict, seuil: float | None = None) -> bool:
    """Exclut un projet APProch dont la BORNE BASSE de la plage de montant
    dépasse déjà le seuil PME (ex. '100k - 500k€' -> exclu, '40k - 100k€' ->
    gardé). Une plage non parsable n'est jamais exclue."""
    if seuil is None:
        seuil = config.SEUIL_MONTANT_MAX
    montant_min, _ = parse_montant_range_approch(record.get("montant_estime"))
    if montant_min is None:
        return False
    return montant_min >= seuil


def is_categorie_achat_hors_scope(record: dict) -> bool:
    """Exclut les projets de catégorie 'Fournitures' ou 'Travaux' (hors
    scope PME de conseil). Catégorie absente/inconnue -> non exclue."""
    categorie = (record.get("categorie_achat") or "").strip().lower()
    return categorie in ("fournitures", "travaux")


def filter_and_classify_approch(records: list[dict]) -> list[dict]:
    """Applique aux projets APProch les mêmes filtres que pour le BOAMP
    (domaine IT — y compris l'exclusion maintenance/acquisition/fourniture —,
    seuil de montant, exclusion catégorie fournitures/travaux), adaptés aux
    champs disponibles pour cette source prévisionnelle.

    IMPORTANT : la "date prévisionnelle de publication" n'est PAS utilisée
    comme critère d'exclusion. Constaté empiriquement : cette date est une
    intention de calendrier de l'acheteur, pas un indicateur fiable
    d'obsolescence — de nombreux projets réellement toujours ouverts
    affichent une date prévisionnelle largement dépassée simplement parce
    que l'administration a pris du retard sur son propre calendrier (le
    champ "statut" APProch, censé refléter l'état réel, vaut "Ouvert" pour
    la quasi-totalité des projets et n'est donc pas discriminant non plus).
    Exclure sur cette base a fait disparaître à tort des opportunités
    pertinentes. Seule la date limite de remise des offres (`date_limite`),
    quand elle est renseignée, est une échéance ferme : un projet est exclu
    si elle est déjà passée ou à moins de `config.DELAI_MIN_SOUMISSION_JOURS`
    jours. Comme pour le BOAMP, les projets classés "hors IT" sont exclus du
    résultat (jamais écrits dans l'Excel)."""
    output: list[dict] = []

    for record in records:
        if is_montant_approch_hors_cible(record):
            continue
        if is_categorie_achat_hors_scope(record):
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
