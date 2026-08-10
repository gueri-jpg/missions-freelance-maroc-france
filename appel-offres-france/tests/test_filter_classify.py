"""Tests des règles métier de filtrage/classification (filter_classify.py)."""
from __future__ import annotations

import datetime as dt

from filter_classify import (
    check_procedure,
    classify_domain,
    filter_and_classify,
    filter_and_classify_approch,
    is_accord_cadre_excluded,
    is_avis_non_appel_offre,
    is_categorie_achat_hors_scope,
    is_deadline_passed,
    is_deadline_too_soon,
    is_date_too_old,
    is_montant_approch_hors_cible,
    is_pure_fourniture,
    parse_montant_range_approch,
)


def _base_record(**overrides) -> dict:
    record = {
        "id": "TEST-1",
        "objet": "",
        "descripteur_libelle": [],
        "cpv": [],
        "accord_cadre": False,
        "montant_estime": None,
        "type_procedure": None,
        "procedure_libelle": "",
        "type_marche": ["SERVICES"],
    }
    record.update(overrides)
    return record


def _approch_record(**overrides) -> dict:
    record = {
        "id": "APPROCH-1",
        "objet": "",
        "description": "",
        "cpv": [],
        "montant_estime": None,
        "categorie_achat": "Services",
    }
    record.update(overrides)
    return record


def test_amo_btp_cpv71_travaux_est_hors_it():
    record = _base_record(
        objet="Mission d'AMO pour travaux de rénovation d'un bâtiment scolaire",
        cpv=["71000000"],
    )
    assert classify_domain(record) == "hors IT"


def test_dev_it_cpv72_est_it_confirme():
    record = _base_record(
        objet="Développement d'une application web de gestion interne",
        cpv=["72212000"],
    )
    assert classify_domain(record) == "IT confirmé"


def test_power_bi_est_garde():
    record = _base_record(
        objet="Accompagnement à la mise en oeuvre d'un outil Power BI",
        cpv=[],
    )
    domaine = classify_domain(record)
    assert domaine in ("IT confirmé", "à vérifier")
    # Vérifie surtout que la ligne n'est jamais classée hors IT / supprimée
    assert domaine != "hors IT"


def test_ambigu_cpv71_avec_mot_it_reste_a_verifier():
    record = _base_record(
        objet="Mission d'assistance pour la mise en place d'un système d'information de suivi de travaux",
        cpv=["71000000"],
    )
    assert classify_domain(record) == "à vérifier"


def test_amoa_ecologie_sans_contexte_it_est_hors_it():
    """Cas réel détecté en collecte : 'AMO écologue' contient 'maîtrise
    d'ouvrage' (terme générique) mais aucun terme IT — doit être exclu, pas
    confirmé IT."""
    record = _base_record(
        objet="Assistance à maîtrise d'ouvrage écologue pour la restauration de 3 sites dans le cadre de mesures compensatoires",
        cpv=[],
    )
    assert classify_domain(record) == "hors IT"


def test_amoa_accessibilite_batiment_scolaire_est_hors_it():
    record = _base_record(
        objet="Mandat de maîtrise d'ouvrage dans le cadre de la mise en accessibilité des cités scolaires",
        cpv=[],
    )
    assert classify_domain(record) == "hors IT"


def test_amoa_signaletique_est_hors_it():
    record = _base_record(
        objet="Assistance à maîtrise d'ouvrage pour la création de signalétique directionnelle des zones d'activités",
        cpv=[],
    )
    assert classify_domain(record) == "hors IT"


def test_amoa_sans_contexte_ni_exclusion_est_hors_it():
    """Terme ambigu ('AMOA') sans aucun co-terme IT ET sans mot d'exclusion
    connu -> AMOA étant un métier transversal (utilisé pour l'assurance,
    l'urbanisme, l'énergie...), l'absence totale de signal IT vaut hors
    scope plutôt que 'à vérifier'. Cas réel : sur un lot de 54 avis "à
    vérifier" avant ce correctif, 52 étaient de l'AMOA hors IT générique."""
    record = _base_record(objet="Assistant maîtrise d'ouvrage en assurance AMOA", cpv=[])
    assert classify_domain(record) == "hors IT"


def test_amoa_apostrophe_typographique_est_reconnue():
    """Les avis BOAMP réels utilisent presque toujours l'apostrophe
    typographique ('’') plutôt que l'apostrophe simple ('\'') utilisée dans
    les listes de mots-clés — sans normalisation, 'maîtrise d’ouvrage' ne
    matchait jamais 'maîtrise d'ouvrage'."""
    record = _base_record(
        objet="Assistance juridique et financière à maîtrise d’ouvrage en assurance",
        cpv=[],
    )
    assert classify_domain(record) == "hors IT"


def test_amoa_avec_systeme_information_apostrophe_typographique_est_it_confirme():
    record = _base_record(
        objet="Assistance à maîtrise d’ouvrage pour la refonte du système d’information comptable",
        cpv=[],
    )
    assert classify_domain(record) == "IT confirmé"


def test_amoa_avec_systeme_information_est_it_confirme():
    record = _base_record(
        objet="Assistance à maîtrise d'ouvrage pour la refonte du système d'information comptable",
        cpv=[],
    )
    assert classify_domain(record) == "IT confirmé"


def test_amoa_acquisition_logiciel_est_it_confirme():
    record = _base_record(
        objet="Assistance à maîtrise d'ouvrage pour l'acquisition d'un logiciel de facturation et de gestion des usagers",
        cpv=[],
    )
    assert classify_domain(record) == "IT confirmé"


def test_procedure_vide_non_exclue_par_adaptee():
    record = _base_record(type_procedure=None, procedure_libelle="Procédure NC")
    garder, statut = check_procedure(record, adaptee_only=True)
    assert garder is True
    assert statut == "procédure à vérifier"


def test_procedure_vide_sans_libelle_non_exclue_par_adaptee():
    record = _base_record(type_procedure=None, procedure_libelle="")
    garder, statut = check_procedure(record, adaptee_only=True)
    assert garder is True
    assert statut == "procédure à vérifier"


def test_procedure_adaptee_gardee_avec_flag():
    record = _base_record(type_procedure="PROCEDURE_ADAPTE", procedure_libelle="Procédure Adaptée")
    garder, statut = check_procedure(record, adaptee_only=True)
    assert garder is True
    assert statut == "Procédure Adaptée"


def test_procedure_ouverte_exclue_avec_flag_adaptee():
    record = _base_record(type_procedure="OUVERT", procedure_libelle="Procédure Ouverte")
    garder, statut = check_procedure(record, adaptee_only=True)
    assert garder is False


def test_procedure_ouverte_gardee_sans_flag_adaptee():
    record = _base_record(type_procedure="OUVERT", procedure_libelle="Procédure Ouverte")
    garder, statut = check_procedure(record, adaptee_only=False)
    assert garder is True


def test_accord_cadre_gros_montant_exclu():
    record = _base_record(accord_cadre=True, montant_estime="9 700 000")
    assert is_accord_cadre_excluded(record) is True


def test_marche_simple_sans_montant_garde():
    record = _base_record(accord_cadre=False, montant_estime=None)
    assert is_accord_cadre_excluded(record) is False


def test_accord_cadre_sans_montant_connu_garde():
    record = _base_record(accord_cadre=True, montant_estime=None)
    assert is_accord_cadre_excluded(record) is False


def test_accord_cadre_petit_montant_garde():
    record = _base_record(accord_cadre=True, montant_estime="45000")
    assert is_accord_cadre_excluded(record) is False


def test_filter_and_classify_exclut_accord_cadre_et_hors_it():
    records = [
        _base_record(id="A", objet="Travaux de voirie", cpv=["45000000"], accord_cadre=False),
        _base_record(id="B", objet="Accord-cadre développement logiciel", cpv=["72212000"],
                     accord_cadre=True, montant_estime="9700000"),
        _base_record(id="C", objet="Marché simple de développement d'une application de gestion", cpv=["72212000"]),
    ]
    result = filter_and_classify(records, adaptee_only=False)
    ids = [r["id"] for r in result]
    assert "B" not in ids  # accord-cadre trop gros -> exclu
    assert "A" not in ids  # hors IT -> exclu de l'Excel (hors scope)
    assert "C" in ids
    domaines = {r["id"]: r["domaine"] for r in result}
    assert domaines["C"] == "IT confirmé"


def test_is_avis_non_appel_offre_exclut_attribution():
    record = _base_record(nature_categorise="attribution/standard")
    assert is_avis_non_appel_offre(record) is True


def test_is_avis_non_appel_offre_garde_appeloffre():
    for nature in ("appeloffre/standard", "appeloffre/concession", "APPELOFFRE/CONCOURS"):
        record = _base_record(nature_categorise=nature)
        assert is_avis_non_appel_offre(record) is False


def test_is_avis_non_appel_offre_nature_absente_non_exclue():
    record = _base_record(nature_categorise=None)
    assert is_avis_non_appel_offre(record) is False


def test_filter_and_classify_exclut_avis_attribution_resultat_de_marche():
    """Un avis d'attribution ('résultats de marché') décrit un contrat déjà
    conclu — ce n'est plus une opportunité active, même si son objet est
    bien du développement logiciel."""
    records = [
        _base_record(id="OUVERT", objet="Développement logiciel de gestion", cpv=["72212000"],
                     nature_categorise="appeloffre/standard"),
        _base_record(id="ATTRIBUE", objet="Développement logiciel de gestion", cpv=["72212000"],
                     nature_categorise="attribution/standard"),
    ]
    result = filter_and_classify(records)
    ids = [r["id"] for r in result]
    assert "OUVERT" in ids
    assert "ATTRIBUE" not in ids


# ---------------------------------------------------------------------------
# Nouvelles règles : hors scope maintenance / acquisition / fournitures
# ---------------------------------------------------------------------------

def test_acquisition_licences_reste_hors_it_malgre_mot_cle_fort():
    """'Acquisition de licences Business Intelligence' doit être exclu
    malgré la présence de 'Business Intelligence' — la nature du marché
    (achat de licences) prime sur le sujet."""
    record = _base_record(
        objet="Acquisition de licences Business Intelligence et reprise de la maintenance de ces licences",
        cpv=["72267000"],
    )
    assert classify_domain(record) == "hors IT"


def test_acquisition_materiel_hors_it():
    record = _base_record(objet="Acquisition de matériel informatique pour les écoles", cpv=[])
    assert classify_domain(record) == "hors IT"


def test_fourniture_de_materiel_hors_it():
    record = _base_record(objet="Fourniture de matériel informatique et de licences bureautiques", cpv=["30200000"])
    assert classify_domain(record) == "hors IT"


def test_acquisition_solution_logicielle_mots_non_adjacents_hors_it():
    """Cas réel détecté en collecte : les mots ne sont pas adjacents
    ('solution logicielle' au lieu de 'logiciel' juste après
    'acquisition') — la détection par co-occurrence doit quand même
    fonctionner, contrairement à un matching de phrase exacte."""
    record = _base_record(
        objet="Acquisition et installation d'une solution logicielle de système d'information des ressources humaines",
        cpv=["72268000"],
    )
    assert classify_domain(record) == "hors IT"


def test_fourniture_dun_logiciel_singulier_hors_it():
    """Cas réel détecté en collecte : 'fourniture d'un logiciel' (singulier)
    ne correspondait à aucune phrase figée existante."""
    record = _base_record(objet="Fourniture d'un logiciel de gestion de la formation des personnels", cpv=[])
    assert classify_domain(record) == "hors IT"


def test_fourniture_de_prestations_nest_pas_une_exclusion():
    """'Fourniture de prestations' est une tournure administrative courante
    signifiant 'prestation de service' — ne doit jamais déclencher
    l'exclusion à elle seule, même avec un objet matériel dans le texte."""
    record = _base_record(
        objet="Fourniture de prestations de développement logiciel et de maintien en conditions opérationnelles du système d'information",
        cpv=["72212000"],
    )
    assert classify_domain(record) == "IT confirmé"


def test_acquisition_hebergement_maintenance_logiciel_mots_eparpilles_hors_it():
    """Cas réel détecté en collecte : 'acquisition' et 'logiciel' séparés
    par 'hébergement et maintenance' — pas de phrase adjacente possible."""
    record = _base_record(
        objet="Acquisition, hébergement et maintenance d'un logiciel métier Finances pour les besoins de la collectivité",
        cpv=["48000000"],
    )
    assert classify_domain(record) == "hors IT"


def test_tma_seule_sans_autre_signal_nest_plus_it_confirme():
    """TMA/infogérance seule (sans mot-clé IT fort) est désormais hors scope
    (mission de maintenance récurrente, pas de projet)."""
    record = _base_record(objet="Marché de TMA sur l'application de paie", cpv=["72212000"])
    assert classify_domain(record) == "à vérifier"


def test_infogerance_avec_terme_fort_reste_it_confirme():
    record = _base_record(objet="Prestations d'infogérance du système d'information", cpv=["72212000"])
    # "infogérance" est exclusion mais "système d'information" est un terme fort -> reste confirmé
    assert classify_domain(record) == "IT confirmé"


def test_infogerance_seule_sans_terme_fort_est_ambigue():
    record = _base_record(objet="Marché d'infogérance du parc informatique", cpv=["72212000"])
    assert classify_domain(record) == "à vérifier"


def test_developpement_et_maintenance_reste_it_confirme():
    """Un marché mixte développement+maintenance reste IT confirmé tant
    qu'un terme IT fort (ex. 'développement logiciel') est présent."""
    record = _base_record(
        objet="Développement logiciel et maintenance corrective d'une solution de gestion RH",
        cpv=["72212000"],
    )
    assert classify_domain(record) == "IT confirmé"


def test_is_pure_fourniture_exclut_fourniture_sans_service():
    record = _base_record(type_marche=["FOURNITURES"])
    assert is_pure_fourniture(record) is True


def test_is_pure_fourniture_garde_si_services_present():
    record = _base_record(type_marche=["FOURNITURES", "SERVICES"])
    assert is_pure_fourniture(record) is False


def test_is_pure_fourniture_garde_si_type_marche_vide():
    record = _base_record(type_marche=[])
    assert is_pure_fourniture(record) is False


def test_is_pure_fourniture_exclut_travaux_pur():
    record = _base_record(type_marche=["TRAVAUX"])
    assert is_pure_fourniture(record) is True


# ---------------------------------------------------------------------------
# Filtrage APProch (parsing de plage de montant, catégorie d'achat)
# ---------------------------------------------------------------------------

def test_parse_montant_range_approch_plage_simple():
    assert parse_montant_range_approch("40k - 100k€") == (40000.0, 100000.0)


def test_parse_montant_range_approch_plage_grande():
    assert parse_montant_range_approch("100k - 500k€") == (100000.0, 500000.0)


def test_parse_montant_range_approch_plus():
    montant_min, montant_max = parse_montant_range_approch("+ 100M€")
    assert montant_min == 100_000_000.0
    assert montant_max is None


def test_parse_montant_range_approch_absent():
    assert parse_montant_range_approch(None) == (None, None)
    assert parse_montant_range_approch("") == (None, None)


def test_is_montant_approch_hors_cible_exclut_borne_basse_trop_haute():
    record = _approch_record(montant_estime="100k - 500k€")
    assert is_montant_approch_hors_cible(record) is True


def test_is_montant_approch_hors_cible_garde_dans_la_cible():
    record = _approch_record(montant_estime="40k - 100k€")
    assert is_montant_approch_hors_cible(record) is False


def test_is_montant_approch_hors_cible_garde_si_non_parsable():
    record = _approch_record(montant_estime="montant non communiqué")
    assert is_montant_approch_hors_cible(record) is False


def test_is_categorie_achat_hors_scope_fournitures():
    record = _approch_record(categorie_achat="Fournitures")
    assert is_categorie_achat_hors_scope(record) is True


def test_is_categorie_achat_hors_scope_travaux():
    record = _approch_record(categorie_achat="Travaux")
    assert is_categorie_achat_hors_scope(record) is True


def test_is_categorie_achat_hors_scope_services_garde():
    record = _approch_record(categorie_achat="Services")
    assert is_categorie_achat_hors_scope(record) is False


def test_filter_and_classify_approch_applique_tous_les_filtres():
    records = [
        _approch_record(id="P1", objet="Développement d'un outil de gestion", montant_estime="40k - 100k€", categorie_achat="Services", cpv=["72212000"]),
        _approch_record(id="P2", objet="Refonte du système d'information RH", montant_estime="5M - 10M€", categorie_achat="Services", cpv=["72212000"]),
        _approch_record(id="P3", objet="Acquisition de matériel informatique", montant_estime="40k - 100k€", categorie_achat="Fournitures", cpv=[]),
        _approch_record(id="P4", objet="Travaux de réfection de voirie", montant_estime="40k - 100k€", categorie_achat="Travaux", cpv=[]),
    ]
    result = filter_and_classify_approch(records)
    ids = [r["id"] for r in result]
    assert ids == ["P1"]  # P2 trop gros, P3 fourniture, P4 travaux
    assert result[0]["domaine"] == "IT confirmé"


# ---------------------------------------------------------------------------
# Filtrage des dates passées (deadlines expirées)
# ---------------------------------------------------------------------------

def test_is_deadline_passed_date_passee():
    record = _base_record(date_limite="2020-01-15T12:00:00+00:00")
    assert is_deadline_passed(record, "date_limite", today=dt.date(2026, 7, 8)) is True


def test_is_deadline_passed_date_future_gardee():
    record = _base_record(date_limite="2027-01-15T12:00:00+00:00")
    assert is_deadline_passed(record, "date_limite", today=dt.date(2026, 7, 8)) is False


def test_is_deadline_passed_date_absente_gardee():
    record = _base_record(date_limite=None)
    assert is_deadline_passed(record, "date_limite") is False


def test_is_deadline_passed_date_non_parsable_gardee():
    record = _base_record(date_limite="date non communiquée")
    assert is_deadline_passed(record, "date_limite") is False


def test_is_deadline_too_soon_moins_de_7_jours_exclue():
    today = dt.date(2026, 7, 9)
    record = _base_record(date_limite="2026-07-14")  # 5 jours
    assert is_deadline_too_soon(record, min_days=7, today=today) is True


def test_is_deadline_too_soon_exactement_7_jours_gardee():
    today = dt.date(2026, 7, 9)
    record = _base_record(date_limite="2026-07-16")  # 7 jours
    assert is_deadline_too_soon(record, min_days=7, today=today) is False


def test_is_deadline_too_soon_date_passee_exclue():
    today = dt.date(2026, 7, 9)
    record = _base_record(date_limite="2026-07-01")
    assert is_deadline_too_soon(record, min_days=7, today=today) is True


def test_is_deadline_too_soon_date_lointaine_gardee():
    today = dt.date(2026, 7, 9)
    record = _base_record(date_limite="2026-09-01")
    assert is_deadline_too_soon(record, min_days=7, today=today) is False


def test_is_deadline_too_soon_date_absente_gardee():
    record = _base_record(date_limite=None)
    assert is_deadline_too_soon(record) is False


def test_filter_and_classify_exclut_deadline_trop_proche():
    today = dt.date.today()
    records = [
        _base_record(id="TROP-PROCHE", objet="Développement logiciel", cpv=["72212000"],
                     date_limite=(today + dt.timedelta(days=3)).isoformat()),
        _base_record(id="OK", objet="Développement logiciel", cpv=["72212000"],
                     date_limite=(today + dt.timedelta(days=30)).isoformat()),
    ]
    result = filter_and_classify(records)
    ids = [r["id"] for r in result]
    assert "TROP-PROCHE" not in ids
    assert "OK" in ids


def test_filter_and_classify_approch_exclut_deadline_trop_proche():
    today = dt.date.today()
    records = [
        _approch_record(id="TROP-PROCHE", objet="Développement logiciel", montant_estime="40k - 100k€",
                         date_limite=(today + dt.timedelta(days=2)).isoformat()),
        _approch_record(id="OK", objet="Développement logiciel", montant_estime="40k - 100k€",
                         date_limite=(today + dt.timedelta(days=30)).isoformat()),
    ]
    result = filter_and_classify_approch(records)
    ids = [r["id"] for r in result]
    assert "TROP-PROCHE" not in ids
    assert "OK" in ids


def test_filter_and_classify_exclut_date_limite_passee():
    records = [
        _base_record(id="A", objet="Développement logiciel", cpv=["72212000"],
                     date_limite="2020-01-01T12:00:00+00:00"),
        _base_record(id="B", objet="Développement logiciel", cpv=["72212000"],
                     date_limite="2027-01-01T12:00:00+00:00"),
    ]
    result = filter_and_classify(records, adaptee_only=False)
    ids = [r["id"] for r in result]
    assert "A" not in ids
    assert "B" in ids


def test_filter_and_classify_approch_ignore_date_previsionnelle_ancienne():
    """La date prévisionnelle de publication n'est PAS un critère d'exclusion
    (constaté empiriquement : elle reflète le calendrier annoncé par
    l'acheteur, pas l'état réel du besoin — un projet toujours pertinent
    peut afficher une date largement dépassée). Un cas réel : 'Développement
    du logiciel GMAO' (CPV 72212000, statut Ouvert) avait une date
    prévisionnelle vieille de 183 jours et était pourtant une opportunité
    valide, exclue à tort par une version antérieure de ce filtre."""
    records = [
        _approch_record(id="P1", objet="Développement logiciel", montant_estime="40k - 100k€",
                         date_previsionnelle_publication="2020-01-01"),
        _approch_record(id="P2", objet="Développement logiciel", montant_estime="40k - 100k€",
                         date_previsionnelle_publication="2027-01-01"),
    ]
    result = filter_and_classify_approch(records)
    ids = [r["id"] for r in result]
    assert "P1" in ids
    assert "P2" in ids


def test_filter_and_classify_approch_exclut_toujours_date_limite_passee():
    """La date limite de remise des offres, quand elle est renseignée, reste
    une échéance ferme (contrairement à la date prévisionnelle de
    publication)."""
    record = _approch_record(
        id="P-EXPIRE", objet="Développement logiciel", montant_estime="40k - 100k€",
        date_limite="2020-01-01",
    )
    result = filter_and_classify_approch([record])
    assert result == []


def test_is_date_too_old_fenetre_de_grace():
    today = dt.date(2026, 7, 9)
    # Passée depuis 10 jours -> dans la fenêtre de grâce de 20 jours -> gardée
    recent = _base_record(date_limite="2026-06-29")
    assert is_date_too_old(recent, "date_limite", max_age_days=20, today=today) is False
    # Passée depuis 30 jours -> hors fenêtre -> exclue
    old = _base_record(date_limite="2026-06-09")
    assert is_date_too_old(old, "date_limite", max_age_days=20, today=today) is True
