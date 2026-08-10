"""Tests de downloader.py — logique pure (repli sans URL, détection de page
de connexion, extraction de liens), sans navigateur réel."""
from __future__ import annotations

from pathlib import Path

import downloader


def test_download_dce_sans_url_renvoie_statut_manuel(tmp_path: Path):
    result = downloader.download_dce("", tmp_path)
    assert result.status == downloader.STATUT_MANUEL


class _FakeAnchor:
    def __init__(self, href):
        self._href = href

    def get_attribute(self, name):
        return self._href if name == "href" else None


class _FakeLocator:
    def __init__(self, items=None, count=0, text=""):
        self._items = items or []
        self._count = count
        self._text = text

    def count(self):
        return self._count

    def all(self):
        return self._items

    def inner_text(self, timeout=None):
        return self._text


class _FakePage:
    def __init__(self, anchors=None, has_password_field=False, body_text=""):
        self._anchors = [_FakeAnchor(h) for h in (anchors or [])]
        self._has_password_field = has_password_field
        self._body_text = body_text

    def locator(self, selector):
        if selector == "input[type=password]":
            return _FakeLocator(count=1 if self._has_password_field else 0)
        if selector == "a":
            return _FakeLocator(items=self._anchors)
        if selector == "body":
            return _FakeLocator(text=self._body_text)
        return _FakeLocator()


def test_looks_like_login_page_detecte_champ_mot_de_passe():
    page = _FakePage(has_password_field=True)
    assert downloader._looks_like_login_page(page) is True


def test_looks_like_login_page_detecte_texte_evocateur():
    page = _FakePage(body_text="Veuillez saisir votre identifiant et votre mot de passe pour vous connecter")
    assert downloader._looks_like_login_page(page) is True


def test_looks_like_login_page_page_normale_non_detectee():
    page = _FakePage(body_text="Détail de la consultation : développement d'une application de gestion")
    assert downloader._looks_like_login_page(page) is False


def test_collect_document_links_exclut_documents_generiques():
    page = _FakePage(anchors=[
        "/documents/CCTP.pdf",
        "/documents/Guide_utilisateur_PLACE.pdf",
        "/documents/CCAP.pdf",
        "/documents/FAQ.pdf",
        "/documents/annexe.png",
    ])
    links = downloader._collect_document_links(page, "https://exemple-plateforme.fr/avis/123")

    assert any(link.endswith("CCTP.pdf") for link in links)
    assert any(link.endswith("CCAP.pdf") for link in links)
    assert not any("Guide_utilisateur" in link for link in links)
    assert not any("FAQ" in link for link in links)
    assert not any(link.endswith(".png") for link in links)


def test_collect_document_links_deduplique():
    page = _FakePage(anchors=["/CCTP.pdf", "/CCTP.pdf"])
    links = downloader._collect_document_links(page, "https://exemple-plateforme.fr/avis/123")
    assert len(links) == 1
