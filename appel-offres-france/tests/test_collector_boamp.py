"""Tests de collector_boamp.py — extraction robuste depuis le champ 'donnees'
BOAMP, sur des fixtures reproduisant fidèlement les trois schémas réels
observés en interrogeant l'API (eForms cac:/cbc:, ancien XSD Boamp_v2xx, et
MAPA pour les procédures adaptées)."""
from __future__ import annotations

from collector_boamp import (
    extract_buyer_profile_url,
    extract_criteres_attribution,
    extract_cpv_codes,
    extract_montant,
    find_by_key_suffix,
    is_accord_cadre,
    normalize_boamp_record,
)

# Fixture eForms — reproduit la structure réelle observée sur un avis récent
# (cac:MainCommodityClassification, cac:RequestedTenderTotal, etc.)
DONNEES_EFORMS = {
    "EFORMS": {
        "ContractNotice": {
            "cac:ContractingParty": {
                "cbc:BuyerProfileURI": "https://www.marches-securises.fr",
            },
            "cac:ProcurementProject": {
                "cbc:Name": {"@languageID": "FRA", "#text": "Développement d'une application"},
                "cac:MainCommodityClassification": {
                    "cbc:ItemClassificationCode": {"@listName": "cpv", "#text": "72212000"}
                },
                "cac:AdditionalCommodityClassification": [
                    {"cbc:ItemClassificationCode": {"@listName": "cpv", "#text": "72310000"}},
                ],
                "cac:RequestedTenderTotal": {
                    "cbc:EstimatedOverallContractAmount": {"@currencyID": "EUR", "#text": "85000"}
                },
            },
            "cac:TenderingProcess": {
                "cac:ContractingSystem": [
                    {"cbc:ContractingSystemTypeCode": {"@listName": "framework-agreement", "#text": "none"}},
                ]
            },
        }
    }
}

# Fixture ancien schéma XSD — reproduit un avis "Boamp_v230.xsd" avec
# accord-cadre et critères pondérés.
DONNEES_XSD = {
    "IDENTITE": {
        "URL_PROFIL_ACHETEUR": "https://www.marches-publics.gouv.fr",
    },
    "OBJET": {
        "CPV": [{"PRINCIPAL": "48000000"}, {"PRINCIPAL": "72267000"}],
        "AVIS_IMPLIQUE": {"ACCORD_CADRE": ""},
        "ACCORD_CADRE": {"DUREE_AN": "3", "VALEUR": {"@DEVISE": "EUR", "#text": "9700000.00"}},
    },
    "PROCEDURE": {
        "TYPE_PROCEDURE": {"PROCEDURE_ADAPTE": ""},
        "CRITERES_ATTRIBUTION": {
            "CRITERES_PONDERES": {
                "CRITERE": [
                    {"@POIDS": "60", "#text": "Valeur technique"},
                    {"@POIDS": "40", "#text": "Prix"},
                ]
            }
        },
    },
}


# Fixture MAPA — schéma réellement utilisé par BOAMP pour les procédures
# adaptées (--adaptee), découvert en collecte réelle. Confirme la présence
# de "urlProfilAcheteur" et "criterePondere" (clé "critere"/"criterePCT",
# différente de l'ancien schéma XSD "CRITERE"/"@POIDS"), et l'ABSENCE
# structurelle de CPV/montant dans la section "initial" (non couverts par
# ce schéma simplifié — cf. limites documentées dans le README).
DONNEES_MAPA = {
    "MAPA": {
        "organisme": {
            "acheteurPublic": "CA Provence Verte",
            "urlProfilAcheteur": "https://caprovenceverte.e-marchespublics.com",
        },
        "initial": {
            "description": {"objet": "Assistance à maîtrise d'ouvrage pour un projet numérique"},
            "duree": {"nbMois": "7"},
            "criteres": {
                "criterePondere": [
                    {"criterePCT": "60", "critere": "Valeur technique des prestations"},
                    {"criterePCT": "40", "critere": "Prix de la prestation"},
                ]
            },
            "procedure": {"procedureAdaptee": ""},
        },
    }
}


def test_find_by_key_suffix_ignore_prefixe_cbc():
    result = find_by_key_suffix(DONNEES_EFORMS, "BuyerProfileURI")
    assert result == ["https://www.marches-securises.fr"]


def test_find_by_key_suffix_ignore_prefixe_cac():
    result = find_by_key_suffix(DONNEES_EFORMS, "ProcurementProject")
    assert len(result) == 1
    assert "cac:MainCommodityClassification" in result[0]


def test_find_by_key_suffix_ancien_schema_sans_prefixe():
    result = find_by_key_suffix(DONNEES_XSD, "CPV")
    assert result == [[{"PRINCIPAL": "48000000"}, {"PRINCIPAL": "72267000"}]]


def test_extract_cpv_codes_eforms():
    codes = extract_cpv_codes(DONNEES_EFORMS)
    assert codes == ["72212000", "72310000"]


def test_extract_cpv_codes_ancien_schema():
    codes = extract_cpv_codes(DONNEES_XSD)
    assert codes == ["48000000", "72267000"]


def test_extract_montant_eforms():
    montant, devise = extract_montant(DONNEES_EFORMS)
    assert montant == "85000"
    assert devise == "EUR"


def test_extract_montant_ancien_schema():
    montant, devise = extract_montant(DONNEES_XSD)
    assert montant == "9700000.00"
    assert devise == "EUR"


def test_extract_buyer_profile_url_les_deux_schemas():
    assert extract_buyer_profile_url(DONNEES_EFORMS) == "https://www.marches-securises.fr"
    assert extract_buyer_profile_url(DONNEES_XSD) == "https://www.marches-publics.gouv.fr"


def test_is_accord_cadre_eforms_none_ne_declenche_pas():
    assert is_accord_cadre(DONNEES_EFORMS) is False


def test_is_accord_cadre_ancien_schema_detecte():
    assert is_accord_cadre(DONNEES_XSD) is True


def test_montant_absent_ne_produit_pas_de_valeur_inventee():
    donnees_vide = {"OBJET": {"TITRE_MARCHE": "Test sans montant"}}
    montant, devise = extract_montant(donnees_vide)
    assert montant is None
    assert devise is None


def test_normalize_boamp_record_champs_essentiels(monkeypatch=None):
    import json

    raw_record = {
        "idweb": "24-12345",
        "objet": "Développement d'une application",
        "dateparution": "2024-09-27",
        "datelimitereponse": "2024-10-29T11:00:00+00:00",
        "nomacheteur": "Ville de Test",
        "code_departement": ["75"],
        "procedure_libelle": "Procédure Adaptée",
        "type_procedure": "PROCEDURE_ADAPTE",
        "url_avis": "https://www.boamp.fr/pages/avis/?q=idweb:24-12345",
        "donnees": json.dumps(DONNEES_EFORMS),
    }
    normalized = normalize_boamp_record(raw_record)
    assert normalized["id"] == "24-12345"
    assert normalized["source"] == "BOAMP"
    assert normalized["cpv"] == ["72212000", "72310000"]
    assert normalized["montant_estime"] == "85000"
    assert normalized["accord_cadre"] is False
    assert normalized["lien_profil_acheteur"] == "https://www.marches-securises.fr"


def test_normalize_boamp_record_donnees_manquantes_ne_leve_pas():
    raw_record = {"idweb": "24-99999", "objet": "Test", "donnees": None}
    normalized = normalize_boamp_record(raw_record)
    assert normalized["cpv"] == []
    assert normalized["montant_estime"] is None


def test_extract_buyer_profile_url_schema_mapa():
    assert extract_buyer_profile_url(DONNEES_MAPA) == "https://caprovenceverte.e-marchespublics.com"


def test_extract_criteres_attribution_schema_mapa():
    criteres = extract_criteres_attribution(DONNEES_MAPA)
    assert criteres is not None
    assert "Valeur technique des prestations (60%)" in criteres
    assert "Prix de la prestation (40%)" in criteres


def test_extract_cpv_absent_sur_schema_mapa_ne_leve_pas():
    """Le schéma MAPA (procédures adaptées) ne porte structurellement pas de
    CPV dans sa section 'initial' — comportement réel confirmé en collecte.
    L'extraction doit renvoyer une liste vide, jamais une erreur ni une
    valeur inventée."""
    assert extract_cpv_codes(DONNEES_MAPA) == []
