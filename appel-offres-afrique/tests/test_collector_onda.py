import collector_onda as co


def _listing_html(entries: str) -> str:
    return f"""
    <div class="itl-c" id="item-" style="display:block;">
        <ul class="liste">
            {entries}
        </ul>
    </div>
    """


def _item(title: str, href: str) -> str:
    return f"""
    <li>
        <h2>
            <span>{title}</span>
        </h2>
        <p class="down">
            <a class="suite" href="{href}" title="x">Lire la suite</a>
        </p>
    </li>
    """


def test_clean_date_ddmmyyyy():
    assert co._clean_date_ddmmyyyy("31/07/2026") == "2026-07-31"


def test_clean_date_ddmmyyyy_non_parsable_retourne_none():
    assert co._clean_date_ddmmyyyy("non précisé") is None
    assert co._clean_date_ddmmyyyy(None) is None


def test_parse_date_limite_fr():
    assert co._parse_date_limite_fr("01 septembre 2026 10:00") == "2026-09-01"
    assert co._parse_date_limite_fr("1 août 2026 09:00") == "2026-08-01"


def test_parse_date_limite_fr_mois_inconnu_retourne_none():
    assert co._parse_date_limite_fr("01 blorptembre 2026 10:00") is None


def test_parse_date_limite_fr_non_parsable_retourne_none():
    assert co._parse_date_limite_fr(None) is None
    assert co._parse_date_limite_fr("date à confirmer") is None


def test_parse_listing_rows_reference_standard():
    html = _listing_html(_item(
        "N°125/26/AOO/ONDA (publié le 31/07/2026) - Prestations de gardiennage "
        "et de surveillance de l'Aéropôle -\n                01 septembre 2026 10:00",
        "/Je-suis-Professionnel/x",
    ))
    rows = co.parse_listing_rows(html)
    assert len(rows) == 1
    assert rows[0]["reference"] == "N°125/26/AOO/ONDA"
    assert rows[0]["date_publication"] == "31/07/2026"
    assert rows[0]["objet"] == "Prestations de gardiennage et de surveillance de l'Aéropôle"
    assert rows[0]["date_limite"] == "01 septembre 2026 10:00"
    assert rows[0]["detail_href"] == "/Je-suis-Professionnel/x"


def test_parse_listing_rows_reference_sans_suffixe_onda():
    """Format constaté en direct : 'N°115-26-AOO' sans suffixe '/ONDA'."""
    html = _listing_html(_item(
        "N°115-26-AOO (publié le 21/07/2026) - Maintenance des véhicules de "
        "sauvetage - 13 août 2026 10:00",
        "/x",
    ))
    rows = co.parse_listing_rows(html)
    assert rows[0]["reference"] == "N°115-26-AOO"


def test_parse_listing_rows_reference_avec_espace():
    """Format constaté en direct : 'N° 021/26/AOO/ONDA' avec espace après N°."""
    html = _listing_html(_item(
        "N° 021/26/AOO/ONDA (publié le 21/07/2026) - Fourniture d'équipements "
        "- 13 août 2026 10:00",
        "/x",
    ))
    rows = co.parse_listing_rows(html)
    assert rows[0]["reference"] == "N° 021/26/AOO/ONDA"


def test_parse_listing_rows_objet_avec_tiret_interne():
    """L'objet peut lui-même contenir un tiret ('Lot 1 : ... - Lot 2 : ...') —
    le tiret final avant la date limite doit rester l'ancre correcte grâce au
    format de date très spécifique en fin de chaîne."""
    html = _listing_html(_item(
        "N°120/26/AOO/ONDA (publié le 31/07/2026) - Formation Lot 1 - Lot 2 "
        "- 01 septembre 2026 10:00",
        "/x",
    ))
    rows = co.parse_listing_rows(html)
    assert rows[0]["objet"] == "Formation Lot 1 - Lot 2"


def test_parse_listing_rows_titre_non_reconnu_ignore():
    html = _listing_html("<li><h2><span>Titre imprévu sans le bon format</span></h2>"
                          '<p class="down"><a class="suite" href="/x">Lire la suite</a></p></li>')
    assert co.parse_listing_rows(html) == []


def test_parse_listing_rows_plusieurs_entrees():
    html = _listing_html(
        _item("N°125/26/AOO/ONDA (publié le 31/07/2026) - Gardiennage - 01 septembre 2026 10:00", "/a")
        + _item("N°120/26/AOO/ONDA (publié le 31/07/2026) - Formation - 01 septembre 2026 10:00", "/b")
    )
    rows = co.parse_listing_rows(html)
    assert len(rows) == 2
    assert [r["detail_href"] for r in rows] == ["/a", "/b"]


def test_normalize_onda_record():
    raw = {
        "reference": "N°120/26/AOO/ONDA",
        "date_publication": "31/07/2026",
        "objet": "Formation RED Hat System Administration",
        "date_limite": "01 septembre 2026 10:00",
        "detail_href": "/Je-suis-Professionnel/Appels-d'offres/x",
    }
    record = co.normalize_onda_record(raw)
    assert record["id"] == "MA-ONDA-N°120/26/AOO/ONDA"
    assert record["pays"] == "Maroc"
    assert record["source"] == "ONDA"
    assert record["devise"] == "MAD"
    assert record["acheteur"] == "Office National Des Aéroports (ONDA)"
    assert record["date_publication"] == "2026-07-31"
    assert record["date_limite"] == "2026-09-01"
    assert record["url_avis"].startswith("https://www.onda.ma/")


def test_normalize_onda_record_sans_objet_retourne_none():
    raw = {"reference": "N°1", "objet": None, "detail_href": "/x"}
    assert co.normalize_onda_record(raw) is None


def test_build_absolute_url_encode_accents_et_degre():
    url = co._build_absolute_url("/Je-suis-Professionnel/N°120-Réalisation-l'ONDA")
    assert url.startswith("https://www.onda.ma/")
    assert "N%C2%B0120" in url
    assert "R%C3%A9alisation" in url
    # Les apostrophes littérales sont acceptées telles quelles par le serveur
    # (constaté en direct) — ne doivent pas être encodées.
    assert "l'ONDA" in url


def test_parse_montant_mad_format_marocain():
    assert co._parse_montant_mad("354 000,00") == 354000.0


def test_parse_montant_mad_placeholder_vide_est_none():
    """'_' est le texte affiché par l'ONDA quand le champ n'est pas
    renseigné (constaté en direct) — ne doit jamais devenir un montant."""
    assert co._parse_montant_mad("_") is None
    assert co._parse_montant_mad(None) is None


def _detail_html(caution: str, estimation: str, ref_consultation: str = "1028954", org: str = "o8p") -> str:
    return f"""
    <table>
        <tr><th><p>Caution provisoire (DH)</p><p>(Constitué...)</p></th><td>{caution}</td></tr>
        <tr><th><p>L'estimation du coût des prestations s'élève à</p></th><td>{estimation}</td></tr>
        <tr><th><p>Date limite</p></th><td>01 septembre 2026 10:00</td></tr>
    </table>
    <a href="https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseDetailsConsultation&amp;refConsultation={ref_consultation}&amp;orgAcronyme={org}">Télécharger</a>
    """


def test_fetch_onda_details_parse(monkeypatch):
    html = _detail_html("7 000,00", "354 000,00")

    class FakeResponse:
        ok = True
        text = html

    monkeypatch.setattr(co.requests, "get", lambda *a, **k: FakeResponse())
    details = co.fetch_onda_details("https://example.test/detail")
    assert details["montant_estime_valeur"] == 354000.0
    assert details["caution_provisoire"] == "7 000,00 MAD"
    assert "EntrepriseDemandeTelechargementDce" in details["lien_dce"]
    assert "refConsultation=1028954" in details["lien_dce"]
    assert "orgAcronyme=o8p" in details["lien_dce"]


def test_fetch_onda_details_placeholder_vide_absent(monkeypatch):
    """Reproduit le cas réel observé (formation RedHat/CISCO) : champs
    montant/caution non renseignés ('_')."""
    html = _detail_html("_", "_")

    class FakeResponse:
        ok = True
        text = html

    monkeypatch.setattr(co.requests, "get", lambda *a, **k: FakeResponse())
    details = co.fetch_onda_details("https://example.test/detail")
    assert details["montant_estime_valeur"] is None
    assert details["caution_provisoire"] is None
    assert details["lien_dce"] is not None


def test_fetch_onda_details_erreur_reseau_non_bloquante(monkeypatch):
    def raise_error(*a, **k):
        raise co.requests.RequestException("boom")

    monkeypatch.setattr(co.requests, "get", raise_error)
    assert co.fetch_onda_details("https://example.test/detail") == {}


def test_fetch_onda_details_sans_lien_pmmp(monkeypatch):
    html = "<table><tr><th><p>Caution provisoire (DH)</p></th><td>_</td></tr></table>"

    class FakeResponse:
        ok = True
        text = html

    monkeypatch.setattr(co.requests, "get", lambda *a, **k: FakeResponse())
    details = co.fetch_onda_details("https://example.test/detail")
    assert details["lien_dce"] is None
