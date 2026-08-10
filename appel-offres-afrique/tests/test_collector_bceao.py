import collector_bceao as cb
import config


def _en_cours_html(items: str) -> str:
    return f"""
    <h2 class="ttrNow">Appel d'offres <span>En cours</span></h2>
    {items}
    <h2 class="ttrBefore">Appel d'offres <span>Clos</span></h2>
    <div class="itemDoc views-row"><div class="views-field views-field-nothing"><span class="field-content"><a href="/fr/appels-offres/un-avis-clos">
    <span class="infoFile">publié le <time datetime="00Z">01 janvier 2026</time>
    </span>
    <span class="descFile"><span class="subTtr">AO/OLD/2026  Date limite le <time datetime="00Z">15 janvier 2026</time>
    </span><span class="ttr"> Un avis déjà clos, à ignorer</span> </span>
    <span class="clear"></span>
    </a></span></div></div>
    """


def _item(href: str, date_pub: str, reference: str, date_limite: str, objet: str) -> str:
    return f"""
    <div class="itemDoc views-row"><div class="views-field views-field-nothing"><span class="field-content"><a href="{href}">
    <span class="infoFile">Publié le <time datetime="00Z">{date_pub}</time>
    </span>
    <span class="descFile"><span class="subTtr">{reference}  Date limite le <time datetime="00Z">{date_limite}</time>
    </span><span class="ttr"> {objet}</span> </span>
    <span class="clear"></span>
    </a></span></div></div>
    """


def test_clean_date_fr():
    assert cb._clean_date_fr("05 Août 2026") == "2026-08-05"
    assert cb._clean_date_fr("1 janvier 2026") == "2026-01-01"


def test_clean_date_fr_non_parsable_retourne_none():
    assert cb._clean_date_fr(None) is None
    assert cb._clean_date_fr("date non précisée") is None


def test_clean_reference_code_simple():
    assert cb._clean_reference("AO/Z04/CTF/04/2026") == "AO/Z04/CTF/04/2026"


def test_clean_reference_avec_description_apres_tiret():
    """Constaté en direct : la référence contient parfois une description
    complète après ' - ' — le titre réel est de toute façon capturé
    séparément (span 'ttr'), on ne garde que le code avant le tiret."""
    value = "AC/KO00/APD/010/2026 - Fourniture et pose de revêtement sur les murs"
    assert cb._clean_reference(value) == "AC/KO00/APD/010/2026"


def test_clean_reference_avec_tiret_interne_non_casse():
    """Un tiret SANS espaces autour (interne au code lui-même) ne doit pas
    être coupé — seul ' - ' (espaces des deux côtés) est un séparateur."""
    assert cb._clean_reference("B00/SAPS/00554-2026") == "B00/SAPS/00554-2026"


def test_clean_reference_none_reste_none():
    assert cb._clean_reference(None) is None


def test_parse_listing_rows_ignore_section_clos():
    html = _en_cours_html(_item(
        "/fr/appels-offres/avis-1", "05 Août 2026", "AO/Z04/CTF/04/2026",
        "24 Août 2026", "Sélection d'une prestataire pour la fourniture",
    ))
    rows = cb.parse_listing_rows(html)
    assert len(rows) == 1
    assert rows[0]["reference"] == "AO/Z04/CTF/04/2026"
    assert rows[0]["date_publication"] == "05 Août 2026"
    assert rows[0]["date_limite"] == "24 Août 2026"
    assert rows[0]["objet"] == "Sélection d'une prestataire pour la fourniture"
    assert rows[0]["detail_href"] == "/fr/appels-offres/avis-1"


def test_parse_listing_rows_plusieurs_entrees():
    html = _en_cours_html(
        _item("/a", "05 Août 2026", "REF-1", "24 Août 2026", "Premier avis")
        + _item("/b", "03 Août 2026", "REF-2", "14 Août 2026", "Second avis")
    )
    rows = cb.parse_listing_rows(html)
    assert len(rows) == 2
    assert [r["reference"] for r in rows] == ["REF-1", "REF-2"]


def test_parse_listing_rows_decode_entites_html():
    """Constaté en direct : certains titres BCEAO contiennent des entités
    HTML brutes (&#039; pour l'apostrophe, &amp;...) non décodées par un
    simple regex sur le HTML brut — doivent être converties en texte lisible."""
    html_content = _en_cours_html(_item(
        "/a", "16 Juillet 2026", "B00/SAPS/00554-2026", "14 Septembre 2026",
        "S&#039;election d&#039;un Bureau d&#039;&eacute;tude &amp; suivi",
    ))
    rows = cb.parse_listing_rows(html_content)
    assert rows[0]["objet"] == "S'election d'un Bureau d'étude & suivi"


def test_parse_listing_rows_sans_section_clos():
    """La coupure ne doit pas planter si la page ne contient aucune section
    'Clos' (ex. tout juste après un redesign de page)."""
    html = "<h2 class=\"ttrNow\">Appel d'offres <span>En cours</span></h2>" + _item(
        "/a", "05 Août 2026", "REF-1", "24 Août 2026", "Un avis",
    )
    rows = cb.parse_listing_rows(html)
    assert len(rows) == 1


def test_normalize_bceao_record():
    raw = {
        "detail_href": "/fr/appels-offres/avis-1",
        "date_publication": "05 Août 2026",
        "reference": "AO/Z04/CTF/04/2026",
        "date_limite": "24 Août 2026",
        "objet": "Sélection d'une prestataire pour la fourniture et l'installation de divers équipements",
    }
    record = cb.normalize_bceao_record(raw)
    assert record["id"] == "BCEAO-AO/Z04/CTF/04/2026"
    assert record["pays"] == "UEMOA (BCEAO)"
    assert record["source"] == "BCEAO"
    assert record["acheteur"] == "BCEAO"
    assert record["devise"] == "XOF"
    assert record["date_publication"] == "2026-08-05"
    assert record["date_limite"] == "2026-08-24"
    assert record["url_avis"] == "https://www.bceao.int/fr/appels-offres/avis-1"


def test_normalize_bceao_record_sans_objet_retourne_none():
    raw = {"detail_href": "/a", "objet": None, "reference": "X"}
    assert cb.normalize_bceao_record(raw) is None


def _detail_html_with_pdfs(*pdf_hrefs: str) -> str:
    links = "".join(f'<a href="{h}">Télécharger</a>' for h in pdf_hrefs)
    return f"<html><body>{links}</body></html>"


def test_fetch_bceao_dce_link_ignore_rapports_politique_monetaire(monkeypatch):
    html = _detail_html_with_pdfs(
        "https://www.bceao.int/sites/default/files/2023-07/Rapport%20sur%20la%20politique%20monetaire.pdf",
        "/sites/default/files/2026-08/DAO_Selection_prestataire.pdf",
    )

    class FakeResponse:
        ok = True
        text = html

    monkeypatch.setattr(cb.requests, "get", lambda *a, **k: FakeResponse())
    link = cb.fetch_bceao_dce_link("https://www.bceao.int/fr/appels-offres/avis-1")
    assert link == "https://www.bceao.int/sites/default/files/2026-08/DAO_Selection_prestataire.pdf"


def test_fetch_bceao_dce_link_aucun_pdf_pertinent(monkeypatch):
    html = _detail_html_with_pdfs(
        "https://www.bceao.int/sites/default/files/2023-07/Rapport%20sur%20la%20politique%20monetaire.pdf",
    )

    class FakeResponse:
        ok = True
        text = html

    monkeypatch.setattr(cb.requests, "get", lambda *a, **k: FakeResponse())
    assert cb.fetch_bceao_dce_link("https://www.bceao.int/fr/appels-offres/avis-1") is None


def test_fetch_bceao_dce_link_erreur_reseau_non_bloquante(monkeypatch):
    def raise_error(*a, **k):
        raise cb.requests.RequestException("boom")

    monkeypatch.setattr(cb.requests, "get", raise_error)
    assert cb.fetch_bceao_dce_link("https://www.bceao.int/fr/appels-offres/avis-1") is None


def test_matches_any_keyword_rejette_hors_domaine():
    assert cb._matches_any_keyword("Fourniture et pose de revêtement sur les murs", config.MOTS_CLES_IT) is False
    assert cb._matches_any_keyword("Sélection d'un Traducteur-Réviseur", config.MOTS_CLES_IT) is False


def test_matches_any_keyword_amo_ne_matche_pas_yamoussoukro():
    """Bug réel constaté en direct sur un avis BCEAO réel (Centre de
    Traitement Fiduciaire à Yamoussoukro) : 'amo' matchait par sous-chaîne
    dans 'Yamoussoukro' avec une recherche naïve."""
    text = "Sélection d'une prestataire pour la fourniture et l'installation de divers équipements pour le Centre de Traitement Fiduciaire de la BCEAO à Yamoussoukro"
    assert cb._matches_any_keyword(text, config.MOTS_CLES_IT) is False


def test_matches_any_keyword_accepte_domaine_metier():
    assert cb._matches_any_keyword("Développement d'une application mobile de paiement", config.MOTS_CLES_IT) is True
    assert cb._matches_any_keyword("Mission d'AMOA pour le système d'information", config.MOTS_CLES_IT) is True


def test_collect_filtre_par_mots_cles(monkeypatch):
    """Reproduit le cas réel signalé : sans pré-filtre mots-clés, TOUS les
    avis BCEAO collectés étaient hors du domaine métier (revêtement,
    traduction, déménagement...). Seul un avis avec un vrai signal IT doit
    survivre au niveau collecte, avant même filter_and_classify."""
    html = _en_cours_html(
        _item("/a", "05 Août 2026", "REF-1", "24 Août 2026", "Fourniture et pose de revêtement sur les murs")
        + _item("/b", "05 Août 2026", "REF-2", "24 Août 2026", "Développement d'une application mobile de paiement")
        + _item("/c", "05 Août 2026", "REF-3", "24 Août 2026", "Sélection d'un Traducteur-Réviseur")
    )
    monkeypatch.setattr(cb, "fetch_page", lambda url: html)
    records = cb.collect()
    assert len(records) == 1
    assert records[0]["reference"] == "REF-2"
