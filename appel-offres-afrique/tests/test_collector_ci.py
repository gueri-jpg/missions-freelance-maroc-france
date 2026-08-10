import collector_ci
import config

_SAMPLE_HTML = """
<html><body>
<table>
<thead><tr>
<th>Numéro AO</th><th>Type de marché</th><th>Objet</th>
<th>Autorité Contractante</th><th>Date de publication</th><th>Date limite</th>
</tr></thead>
<tbody>
<tr>
<td>AOO26030423710</td>
<td>Travaux</td>
<td>Construction de douze foyers de jeunes</td>
<td>CONSEIL REGIONAL BAGOUE</td>
<td>12-03-2026</td>
<td>17-04-2026</td>
</tr>
<tr>
<td>F 73 /2024</td>
<td>FOURNITURE</td>
<td>ACQUISITION ET INSTALLATION DE LOGICIELS METIERS AU PROFIT DE L'INP-HB</td>
<td></td>
<td>30-11--0001</td>
<td>20-08-2024</td>
</tr>
<tr>
<td>S 12/2026</td>
<td>PRESTATION</td>
<td>Développement d'une application web de gestion des dossiers</td>
<td>MINISTERE DU NUMERIQUE</td>
<td>01-01-2026</td>
<td>31-12-2026</td>
</tr>
</tbody>
</table>
</body></html>
"""


def test_parse_appel_offre_rows():
    rows = collector_ci.parse_appel_offre_rows(_SAMPLE_HTML)
    assert len(rows) == 3
    assert rows[0]["numero_ao"] == "AOO26030423710"
    assert rows[0]["acheteur"] == "CONSEIL REGIONAL BAGOUE"


def test_parse_appel_offre_rows_sentinel_date_devient_none():
    rows = collector_ci.parse_appel_offre_rows(_SAMPLE_HTML)
    assert rows[1]["date_publication"] is None


def test_parse_appel_offre_rows_acheteur_absent_reste_none():
    rows = collector_ci.parse_appel_offre_rows(_SAMPLE_HTML)
    assert rows[1]["acheteur"] is None


def test_normalize_ci_record():
    raw = {
        "numero_ao": "S 12/2026",
        "type_marche": "PRESTATION",
        "objet": "Développement d'une application web",
        "acheteur": "MINISTERE DU NUMERIQUE",
        "date_publication": "01-01-2026",
        "date_limite": "31-12-2026",
    }
    record = collector_ci.normalize_ci_record(raw)
    assert record["id"] == "CI-S 12/2026"
    assert record["pays"] == "Côte d'Ivoire"
    assert record["devise"] == "XOF"


def test_normalize_ci_record_acheteur_absent_non_precise():
    raw = {
        "numero_ao": "F 73 /2024", "type_marche": "FOURNITURE", "objet": "x",
        "acheteur": None, "date_publication": None, "date_limite": "20-08-2024",
    }
    record = collector_ci.normalize_ci_record(raw)
    assert record["acheteur"] == "non précisé"


def test_collect_filtre_sur_mots_cles_it(monkeypatch):
    monkeypatch.setattr(collector_ci, "fetch_page", lambda: _SAMPLE_HTML)
    results = collector_ci.collect(keywords=["logiciel", "application web"])
    ids = {r["id"] for r in results}
    assert "CI-F 73 /2024" in ids
    assert "CI-S 12/2026" in ids
    assert "CI-AOO26030423710" not in ids


def test_matches_any_keyword_amo_ne_matche_pas_yamoussoukro():
    """Bug réel constaté en direct : 'amo' (ajouté pour couvrir AMO/AMOA/
    PMO) matchait par sous-chaîne à l'intérieur de 'Yamoussoukro' (capitale
    politique de la Côte d'Ivoire) avec une recherche naïve — corrigé en
    déléguant à filter_classify.matches_any_keyword (limite de mot)."""
    text = "Travaux de voirie à Yamoussoukro pour la construction d'un marché"
    assert collector_ci._matches_any_keyword(text, config.MOTS_CLES_IT) is False


def test_matches_any_keyword_amo_matche_bien_amo_isole():
    text = "Mission d'AMO pour le système d'information du ministère"
    assert collector_ci._matches_any_keyword(text, config.MOTS_CLES_IT) is True
