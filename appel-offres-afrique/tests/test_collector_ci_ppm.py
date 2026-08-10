import collector_ci_ppm as ppm


def _raw_row():
    return {
        "N": "3",
        "MINISTERE": "4 - Ministère des Transports",
        "AUTORITE CONTRACTANTE": "Direction Générale des Affaires Maritimes",
        "OBJET DE L'OPERATION": "Développement d'une plateforme de suivi des dossiers",
        "BAILLEUR": "ETAT DE COTE D'IVOIRE",
        "LIGNE BUDGETAIRE": "PM24111179103-233900",
        "TYPE DE MARCHE": "Prestation intellectuelle",
        "MODE DE PASSATION": "Appel d'offres ouvert",
        "DATE DE PUBLICATION": "17/06/26",
    }


def test_normalize_ppm_record():
    record = ppm.normalize_ppm_record(_raw_row())
    assert record is not None
    assert record["id"] == "CI-PPM-PM24111179103-233900"
    assert record["pays"] == "Côte d'Ivoire"
    assert record["montant_remarque"] == "estimation prévisionnelle — à confirmer"
    assert record["date_limite"] is None


def test_normalize_ppm_record_sans_objet_retourne_none():
    raw = _raw_row()
    raw["OBJET DE L'OPERATION"] = ""
    assert ppm.normalize_ppm_record(raw) is None


def test_normalize_ppm_record_sans_ligne_budgetaire_id_fallback():
    raw = _raw_row()
    raw["LIGNE BUDGETAIRE"] = ""
    record = ppm.normalize_ppm_record(raw)
    assert record is not None
    assert record["id"].startswith("CI-PPM-")
    assert record["reference"] == "non précisé"


def test_find_col_insensible_a_la_casse_et_aux_accents():
    raw = _raw_row()
    assert ppm._find_col(raw, "minist") == "4 - Ministère des Transports"
    assert ppm._find_col(raw, "autorite", "contractante") == "Direction Générale des Affaires Maritimes"
