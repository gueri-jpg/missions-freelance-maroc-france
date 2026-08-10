import collector_bad as cbad
import config


def _rss(items: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel><title>Test</title>
    {items}
    </channel></rss>"""


def _item(title: str, link: str, pub_date: str, guid: str) -> str:
    return f"""
    <item>
        <title>{title}</title>
        <link>{link}</link>
        <pubDate>{pub_date}</pubDate>
        <guid isPermaLink="true">{guid}</guid>
    </item>
    """


def test_strip_accents():
    assert cbad._strip_accents("Côte d'Ivoire") == "Cote d'Ivoire"


def test_matches_country_insensible_accents():
    assert cbad._matches_country("Cote d'Ivoire", "Côte d'Ivoire") is True
    assert cbad._matches_country("Côte d'Ivoire", "Cote d'Ivoire") is True


def test_matches_country_apostrophe_typographique():
    assert cbad._matches_country("Côte d’Ivoire", "Côte d'Ivoire") is True


def test_matches_country_pays_different_ne_matche_pas():
    assert cbad._matches_country("Togo", "Côte d'Ivoire") is False


def test_matches_country_absent_ne_matche_pas():
    assert cbad._matches_country(None, "Côte d'Ivoire") is False


def test_parse_rfc822_date():
    assert cbad._parse_rfc822_date("Thu, 30 Jul 2026 18:17:50 +0000") == "2026-07-30"


def test_parse_rfc822_date_non_parsable_retourne_none():
    assert cbad._parse_rfc822_date(None) is None
    assert cbad._parse_rfc822_date("pas une date") is None


def test_extract_node_id():
    assert cbad._extract_node_id("https://www.afdb.org/node/95899") == "95899"
    assert cbad._extract_node_id("https://www.afdb.org/en/corporate-procurement/some-title-95899") == "95899"


def test_extract_node_id_sans_chiffres_retourne_none():
    assert cbad._extract_node_id("https://www.afdb.org/en/corporate-procurement/no-id-here") is None
    assert cbad._extract_node_id(None) is None


def test_parse_rss_items():
    xml_text = _rss(_item(
        "AMI - Togo - Élaboration de rapports",
        "https://www.afdb.org/en/x", "Thu, 30 Jul 2026 18:17:50 +0000",
        "https://www.afdb.org/node/123",
    ))
    items = cbad.parse_rss_items(xml_text)
    assert len(items) == 1
    assert items[0]["title"] == "AMI - Togo - Élaboration de rapports"
    assert items[0]["link"] == "https://www.afdb.org/en/x"
    assert items[0]["guid"] == "https://www.afdb.org/node/123"


def test_parse_rss_items_xml_invalide_retourne_liste_vide():
    assert cbad.parse_rss_items("<rss><channel><item><title>") == []


def test_normalize_project_record_titre_structure():
    raw = {
        "title": "AMI - Togo - Élaboration de rapports d&#039;achèvement pour le projet",
        "link": "https://www.afdb.org/en/x-123",
        "pub_date": "Thu, 30 Jul 2026 18:17:50 +0000",
        "guid": "https://www.afdb.org/node/123",
    }
    record = cbad.normalize_project_record(raw)
    assert record["type_marche"] == "AMI"
    assert record["_pays_pour_filtre"] == "Togo"
    assert record["objet"] == "Élaboration de rapports d'achèvement pour le projet"
    assert record["lieu_execution"] == "Togo"
    assert record["date_publication"] == "2026-07-30"
    assert record["id"] == "BAD-PROJ-123"
    assert record["devise"] is None


def test_normalize_project_record_titre_avec_tirets_supplementaires():
    """'AMI - Bénin - Ingénieur Génie Civil - PERU II' : le tiret
    supplémentaire dans la description ne doit pas casser le découpage
    TYPE/Pays (maxsplit sur les deux premiers tirets seulement)."""
    raw = {
        "title": "AMI - Bénin - Ingénieur Génie Civil - PERU II",
        "link": "https://www.afdb.org/en/x-124", "pub_date": None,
        "guid": "https://www.afdb.org/node/124",
    }
    record = cbad.normalize_project_record(raw)
    assert record["type_marche"] == "AMI"
    assert record["_pays_pour_filtre"] == "Bénin"
    assert record["objet"] == "Ingénieur Génie Civil - PERU II"


def test_normalize_project_record_titre_non_structure_garde_titre_entier():
    """Un titre qui ne suit pas le format TYPE - Pays - Description devient
    l'objet complet, sans deviner de type/pays (règle d'exactitude)."""
    raw = {
        "title": "Un titre libre sans structure reconnue",
        "link": "https://www.afdb.org/en/x-125", "pub_date": None,
        "guid": "https://www.afdb.org/node/125",
    }
    record = cbad.normalize_project_record(raw)
    assert record["type_marche"] is None
    assert record["_pays_pour_filtre"] is None
    assert record["objet"] == "Un titre libre sans structure reconnue"


def test_normalize_project_record_sans_titre_retourne_none():
    assert cbad.normalize_project_record({"title": None}) is None


def test_normalize_corporate_record():
    raw = {
        "title": "Static Application Security (SAST) and Software Composition Analysis (SCA) Solution",
        "link": "https://www.afdb.org/en/corporate-procurement/sast-95900",
        "pub_date": "Thu, 30 Jul 2026 18:17:50 +0000",
        "guid": "https://www.afdb.org/node/95900",
    }
    record = cbad.normalize_corporate_record(raw)
    assert record["id"] == "BAD-CORP-95900"
    assert record["source"] == "BAD (corporate)"
    assert record["pays"] == "Afrique (BAD — corporate)"
    assert record["objet"] == raw["title"]
    assert "type_marche" not in record or record["type_marche"] is None


def test_normalize_corporate_record_decode_entites_html():
    raw = {
        "title": "Prestation de service de gestion, d&#039;exploitation et de maintenance",
        "link": "https://www.afdb.org/en/x-1", "pub_date": None, "guid": "https://www.afdb.org/node/1",
    }
    record = cbad.normalize_corporate_record(raw)
    assert record["objet"] == "Prestation de service de gestion, d'exploitation et de maintenance"


def test_collect_project_procurement_filtre_par_pays_et_mot_cle(monkeypatch):
    xml_text = _rss(
        _item("AMI - Togo - Rapport sur le système d'information", "https://www.afdb.org/en/a", "Thu, 30 Jul 2026 00:00:00 +0000", "https://www.afdb.org/node/1")
        + _item("EOI - Côte d'Ivoire - Recrutement d'un gardien", "https://www.afdb.org/en/b", "Thu, 30 Jul 2026 00:00:00 +0000", "https://www.afdb.org/node/2")
        + _item("EOI - Côte d'Ivoire - Étude de faisabilité pour un système d'information", "https://www.afdb.org/en/c", "Thu, 30 Jul 2026 00:00:00 +0000", "https://www.afdb.org/node/3")
    )
    monkeypatch.setattr(cbad, "fetch_rss", lambda url: xml_text)
    records = cbad.collect_project_procurement(country_filter="Côte d'Ivoire")
    # Le premier avis matche le mot-clé mais pas le pays ; le second matche
    # le pays mais aucun mot-clé IT ; seul le troisième matche les deux.
    assert len(records) == 1
    assert records[0]["lieu_execution"] == "Côte d'Ivoire"
    assert "_pays_pour_filtre" not in records[0]
    assert "système d'information" in records[0]["objet"].lower()


def test_fetch_deadline_extrait_date_iso(monkeypatch):
    html_snippet = (
        '<div class="field field-name-field-procurement-end-date">'
        '<span property="dc:date" content="2026-08-20T12:00:00+00:00">20-Aug-2026 12:00</span></div>'
    )

    class FakeResponse:
        ok = True
        text = html_snippet

    monkeypatch.setattr(cbad.requests, "get", lambda *a, **k: FakeResponse())
    assert cbad.fetch_deadline("https://www.afdb.org/en/x") == "2026-08-20"


def test_fetch_deadline_absent_retourne_none(monkeypatch):
    class FakeResponse:
        ok = True
        text = "<html>rien ici</html>"

    monkeypatch.setattr(cbad.requests, "get", lambda *a, **k: FakeResponse())
    assert cbad.fetch_deadline("https://www.afdb.org/en/x") is None


def test_fetch_deadline_url_absente_retourne_none():
    assert cbad.fetch_deadline(None) is None


def test_fetch_deadline_erreur_reseau_non_bloquante(monkeypatch):
    def raise_error(*a, **k):
        raise cbad.requests.RequestException("boom")

    monkeypatch.setattr(cbad.requests, "get", raise_error)
    assert cbad.fetch_deadline("https://www.afdb.org/en/x") is None


def test_matches_any_keyword_rejette_hors_domaine():
    assert cbad._matches_any_keyword("Provision of Cleaning Services", config.MOTS_CLES_IT) is False
    assert cbad._matches_any_keyword("Prestations de services de téléphonie mobile", config.MOTS_CLES_IT) is False


def test_matches_any_keyword_amo_ne_matche_pas_yamoussoukro():
    """Même bug que collector_bceao.py/collector_ci.py, verrouillé ici
    aussi : 'amo' ne doit jamais matcher par sous-chaîne dans 'Yamoussoukro'."""
    text = "Réhabilitation du bureau régional de Yamoussoukro"
    assert cbad._matches_any_keyword(text, config.MOTS_CLES_IT) is False


def test_matches_any_keyword_accepte_domaine_metier_anglais():
    """Cas réel ayant motivé l'ajout des équivalents anglais dans config.py."""
    assert cbad._matches_any_keyword(
        "Static Application Security (SAST) and Software Composition Analysis (SCA) Solution",
        config.MOTS_CLES_IT,
    ) is False  # ni "software development" ni "cybersecurity" ne matchent ce libellé précis (attendu)
    assert cbad._matches_any_keyword("Web Application Development Services", config.MOTS_CLES_IT) is True
    assert cbad._matches_any_keyword("Provision of Cybersecurity Solution", config.MOTS_CLES_IT) is True


def test_collect_corporate_procurement_filtre_par_mots_cles(monkeypatch):
    """Reproduit le cas réel signalé : sans pré-filtre mots-clés, TOUS les
    avis BAD collectés étaient hors du domaine métier (nettoyage,
    téléphonie, recherche de bureaux...)."""
    xml_text = _rss(
        _item("Provision of Cleaning Services", "https://www.afdb.org/en/a", "Thu, 30 Jul 2026 00:00:00 +0000", "https://www.afdb.org/node/1")
        + _item("Web Application Development Services", "https://www.afdb.org/en/b", "Thu, 30 Jul 2026 00:00:00 +0000", "https://www.afdb.org/node/2")
    )
    monkeypatch.setattr(cbad, "fetch_rss", lambda url: xml_text)
    records = cbad.collect_corporate_procurement()
    assert len(records) == 1
    assert records[0]["objet"] == "Web Application Development Services"
