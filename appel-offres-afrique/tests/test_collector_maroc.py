import collector_maroc as cm


def test_clean_label_retire_prefixe_objet():
    assert cm._clean_label("Objet : Développement d'une plateforme") == "Développement d'une plateforme"


def test_clean_label_retire_prefixe_acheteur():
    assert cm._clean_label("Acheteur public : MINISTERE X") == "MINISTERE X"


def test_clean_label_none_reste_none():
    assert cm._clean_label(None) is None


def test_clean_label_vide_retourne_none():
    assert cm._clean_label("Objet :  ") is None


def test_clean_date_format_jj_mm_aaaa():
    assert cm._clean_date("19/11/2026") == "2026-11-19"


def test_clean_date_avec_heure():
    assert cm._clean_date("19/11/2026 10:00") == "2026-11-19"


def test_clean_date_non_parsable_retourne_none():
    assert cm._clean_date("non précisé") is None
    assert cm._clean_date(None) is None


def test_dedupe_tooltip_text_texte_court_identique():
    """Cas réel constaté (info-bulle PRADO) : texte pas assez long pour être
    tronqué, mais la même valeur apparaît quand même deux fois (visible +
    info-bulle cachée), séparées par ' ... '."""
    assert cm._dedupe_tooltip_text("RABAT ... RABAT") == "RABAT"


def test_dedupe_tooltip_text_partie_visible_tronquee():
    """Cas réel constaté (avis PMMP Casablanca Baïa) : la partie visible est
    tronquée à mi-phrase ("... paiement du"), seule l'info-bulle (après
    ' ... ') contient la phrase complète — toujours garder ce qui suit le
    séparateur, jamais ce qui précède."""
    tronque = (
        "Dans le cadre de sa mission, la Société de Développement Local "
        "Casablanca Baïa lance un appel à manifestation d'intérêt pour la "
        "sélection de prestataire pour la mise en place d'une solution "
        "digital de paiement du"
    )
    complet = (
        "Dans le cadre de sa mission, la Société de Développement Local "
        "Casablanca Baïa lance un appel à manifestation d'intérêt pour la "
        "sélection de prestataire pour la mise en place d'une solution "
        "digital de paiement du stationnement et de contrôle terrain"
    )
    assert cm._dedupe_tooltip_text(f"{tronque} ... {complet}") == complet


def test_dedupe_tooltip_text_sans_separateur_inchange():
    assert cm._dedupe_tooltip_text("Développement d'une plateforme web") == "Développement d'une plateforme web"


def test_dedupe_tooltip_text_none_reste_none():
    assert cm._dedupe_tooltip_text(None) is None
    assert cm._dedupe_tooltip_text("") == ""


def test_normalize_maroc_record():
    raw = {
        "reference": "17/2026/MAP",
        "objet": "Objet : Mise à niveau du module de Workflow",
        "acheteur": "Acheteur public : AGENCE MAGHREB ARABE PRESSE",
        "categorie": "Services",
        "procedure": "Appel d'offres ouvert",
        "lieu": "RABAT",
        "date_publication": "08/07/2026",
        "date_limite": "08/09/2026",
        "detail_url": "index.php?page=entreprise.EntrepriseDetailConsultation&refConsultation=123&orgAcronyme=xyz",
    }
    record = cm.normalize_maroc_record(raw)
    assert record["id"] == "MA-17/2026/MAP"
    assert record["pays"] == "Maroc"
    assert record["devise"] == "MAD"
    assert record["objet"] == "Mise à niveau du module de Workflow"
    assert record["acheteur"] == "AGENCE MAGHREB ARABE PRESSE"
    assert record["date_limite"] == "2026-09-08"
    assert "refConsultation=123" in record["url_avis"]
    assert "EntrepriseDemandeTelechargementDce" in record["lien_dce"]
    assert "refConsultation=123" in record["lien_dce"]
    assert "orgAcronyme=xyz" in record["lien_dce"]


def test_normalize_maroc_record_deduplique_objet_et_lieu():
    """Reproduit le bug réel signalé : objet/lieu doublés par le mécanisme
    d'info-bulle PRADO (cf. _dedupe_tooltip_text), même en passant par
    normalize_maroc_record de bout en bout."""
    raw = {
        "reference": "17/2026/MAP",
        "objet": "Objet : Mise à niveau du module de Workflow ... Mise à niveau du module de Workflow",
        "acheteur": "Acheteur public : AGENCE X",
        "lieu": "RABAT ... RABAT",
    }
    record = cm.normalize_maroc_record(raw)
    assert record["objet"] == "Mise à niveau du module de Workflow"
    assert record["lieu_execution"] == "RABAT"


def test_normalize_maroc_record_sans_detail_url_pas_de_dce():
    raw = {"reference": "1", "objet": "Objet : Test", "acheteur": None, "detail_url": None}
    record = cm.normalize_maroc_record(raw)
    assert record["lien_dce"] is None


def test_normalize_maroc_record_sans_objet_retourne_none():
    raw = {"reference": "1", "objet": None, "acheteur": "X"}
    assert cm.normalize_maroc_record(raw) is None


def test_normalize_maroc_record_sans_reference_id_fallback_objet():
    raw = {"reference": None, "objet": "Objet : Un projet quelconque de test", "acheteur": None}
    record = cm.normalize_maroc_record(raw)
    assert record["id"].startswith("MA-")
    assert record["acheteur"] == "non précisé"


def _detail_html(estimation: str, caution: str) -> str:
    return f"""
    <span id="ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_idReferentielZoneText_RepeaterReferentielZoneText_ctl0_labelReferentielZoneText" class="content-bloc">{estimation}</span>
    <span id="ctl0_CONTENU_PAGE_idEntrepriseConsultationSummary_cautionProvisoire">{caution} MAD </span>
    """


def test_parse_montant_mad_format_marocain():
    assert cm._parse_montant_mad("354 000,00") == 354000.0
    assert cm._parse_montant_mad("7 000,00") == 7000.0


def test_parse_montant_mad_zero_est_none():
    """'0,00' est la valeur par défaut du champ quand rien n'est renseigné
    (constaté en direct) — jamais un vrai montant nul."""
    assert cm._parse_montant_mad("0,00") is None
    assert cm._parse_montant_mad(None) is None


def test_fetch_consultation_details_parse(monkeypatch):
    html = _detail_html("354 000,00", "7 000,00")

    class FakeResponse:
        ok = True
        text = html

    monkeypatch.setattr(cm.requests, "get", lambda *a, **k: FakeResponse())
    details = cm.fetch_consultation_details("https://example.test/detail")
    assert details["montant_estime_valeur"] == 354000.0
    assert details["montant_estime"] == "354 000,00 MAD"
    assert details["caution_provisoire"] == "7 000,00 MAD"


def test_fetch_consultation_details_caution_nulle_absente(monkeypatch):
    html = _detail_html("100 000,00", "0,00")

    class FakeResponse:
        ok = True
        text = html

    monkeypatch.setattr(cm.requests, "get", lambda *a, **k: FakeResponse())
    details = cm.fetch_consultation_details("https://example.test/detail")
    assert details["caution_provisoire"] is None
    assert details["montant_estime_valeur"] == 100000.0


def test_fetch_consultation_details_erreur_reseau_non_bloquante(monkeypatch):
    def raise_error(*a, **k):
        raise cm.requests.RequestException("boom")

    monkeypatch.setattr(cm.requests, "get", raise_error)
    assert cm.fetch_consultation_details("https://example.test/detail") == {}
