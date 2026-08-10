"""Tests de collector_place.py — parsing de date et normalisation (logique
pure, sans navigateur)."""
from __future__ import annotations

from collector_place import _parse_month, _parse_place_date, _row_matches_keyword, normalize_place_record
from filter_classify import filter_and_classify


def test_parse_month_abreviations_courantes():
    assert _parse_month("Juil.") == 7
    assert _parse_month("Août") == 8
    assert _parse_month("Juin") == 6
    assert _parse_month("Sept.") == 9
    assert _parse_month("Janv.") == 1
    assert _parse_month("Déc.") == 12


def test_parse_month_inconnu_retourne_none():
    assert _parse_month("Xyz.") is None
    assert _parse_month(None) is None


def test_parse_place_date_complete():
    assert _parse_place_date(["3", "Juil.", "2026"]) == "2026-07-03"
    assert _parse_place_date(["19", "Août", "2026"]) == "2026-08-19"


def test_parse_place_date_composante_manquante_retourne_none():
    assert _parse_place_date(["3", None, "2026"]) is None
    assert _parse_place_date([None, "Juil.", "2026"]) is None
    assert _parse_place_date(None) is None
    assert _parse_place_date(["3", "Juil."]) is None


def test_row_matches_keyword_present_dans_objet():
    raw = {"objet": "Développement d'une application Power BI", "intitule": ""}
    assert _row_matches_keyword(raw, "power bi") is True


def test_row_matches_keyword_absent_rejette():
    """Cas réel : PLACE traite 'power bi' comme un OU entre mots
    individuels et remonte ~200 résultats sans rapport (probablement
    matchés sur 'bi' seul) — la vérification cliente doit les rejeter."""
    raw = {"objet": "Prestations traiteur pour l'université", "intitule": ""}
    assert _row_matches_keyword(raw, "power bi") is False


def test_row_matches_keyword_apostrophe_typographique():
    raw = {"objet": "Refonte du système d’information comptable", "intitule": ""}
    assert _row_matches_keyword(raw, "système d'information") is True


def test_row_matches_keyword_cherche_aussi_dans_intitule():
    raw = {"objet": "", "intitule": "Migration vers Talend"}
    assert _row_matches_keyword(raw, "talend") is True


def _raw_row(**overrides) -> dict:
    row = {
        "procedure_abbr": "MAPA",
        "procedure_libelle": "Procédure adaptée",
        "categorie": "Services",
        "reference": "REF-1",
        "intitule": "Développement d'une application",
        "objet": "Développement d'une application de gestion",
        "organisme": "Ministère Test",
        "lieu": "(75) Paris",
        "date_pub": ["1", "Juin", "2026"],
        "date_limite": ["30", "Juil.", "2026"],
        "consult_url": "https://www.marches-publics.gouv.fr/app.php/entreprise/consultation/1?orgAcronyme=abc",
        "rc_url": None,
    }
    row.update(overrides)
    return row


def test_normalize_place_record_champs_de_base():
    record = normalize_place_record(_raw_row())
    assert record["id"] == "PLACE-REF-1"
    assert record["source"] == "PLACE"
    assert record["date_publication"] == "2026-06-01"
    assert record["date_limite"] == "2026-07-30"
    assert record["acheteur"] == "Ministère Test"
    assert record["type_procedure"] == "PROCEDURE_ADAPTE"
    assert record["type_marche"] == ["SERVICES"]
    assert record["url_avis"].endswith("/consultation/1?orgAcronyme=abc")


def test_normalize_place_record_sans_reference_id_none():
    record = normalize_place_record(_raw_row(reference=None))
    assert record["id"] is None


def test_normalize_place_record_garde_lien_rc_direct():
    rc_url = "https://www.marches-publics.gouv.fr/index.php?page=Entreprise.EntrepriseDownloadReglement&id=xyz"
    record = normalize_place_record(_raw_row(rc_url=rc_url))
    assert record["lien_rc_direct"] == rc_url
    # Le lien RC direct (PDF public sans authentification) est priorisé sur
    # la simple page de consultation pour la colonne profil acheteur/DCE.
    assert record["lien_profil_acheteur"] == rc_url


def test_normalize_place_record_sans_rc_utilise_consult_url_comme_profil():
    record = normalize_place_record(_raw_row(rc_url=None))
    assert record["lien_profil_acheteur"] == record["url_avis"]


def test_normalize_place_record_source_label_maximilien():
    record = normalize_place_record(_raw_row(), source_label="Maximilien")
    assert record["id"] == "MAXIMILIEN-REF-1"
    assert record["source"] == "Maximilien"


def test_normalize_place_record_compatible_avec_filter_and_classify():
    """Le schéma PLACE doit être directement consommable par la même
    filter_and_classify() que BOAMP, sans logique dédiée."""
    records = [
        normalize_place_record(_raw_row(reference="IT-1", objet="Développement logiciel de gestion")),
        normalize_place_record(_raw_row(reference="TRAVAUX-1", categorie="Travaux",
                                         objet="Travaux de réfection de voirie")),
    ]
    result = filter_and_classify(records)
    ids = [r["id"] for r in result]
    assert "PLACE-IT-1" in ids
    assert "PLACE-TRAVAUX-1" not in ids
