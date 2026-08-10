"""Tests de collector_approch.py — résolution SIREN mockée (aucun appel réseau)."""
from __future__ import annotations

import collector_approch


class _FakeResponse:
    def __init__(self, ok: bool, payload: dict | None = None, status_code: int = 200):
        self.ok = ok
        self._payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self._payload


def test_resolve_siren_name_retourne_la_raison_sociale(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        assert params["q"] == "110068012"
        return _FakeResponse(True, {"results": [{"nom_complet": "MINISTERE DE LA TRANSITION ECOLOGIQUE"}]})

    monkeypatch.setattr(collector_approch.requests, "get", fake_get)
    name = collector_approch.resolve_siren_name("110068012")
    assert name == "MINISTERE DE LA TRANSITION ECOLOGIQUE"


def test_resolve_siren_name_siren_introuvable_retourne_none(monkeypatch):
    monkeypatch.setattr(collector_approch.requests, "get", lambda *a, **k: _FakeResponse(True, {"results": []}))
    assert collector_approch.resolve_siren_name("000000000") is None


def test_resolve_siren_name_erreur_reseau_ne_leve_pas(monkeypatch):
    def fake_get(*args, **kwargs):
        raise collector_approch.requests.RequestException("boom")

    monkeypatch.setattr(collector_approch.requests, "get", fake_get)
    assert collector_approch.resolve_siren_name("110068012") is None


def test_resolve_siren_name_siren_vide_retourne_none_sans_appel(monkeypatch):
    def fake_get(*args, **kwargs):
        raise AssertionError("ne doit pas appeler l'API pour un SIREN vide")

    monkeypatch.setattr(collector_approch.requests, "get", fake_get)
    assert collector_approch.resolve_siren_name(None) is None
    assert collector_approch.resolve_siren_name("") is None


def test_resolve_siren_name_utilise_le_cache(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params["q"])
        return _FakeResponse(True, {"results": [{"nom_complet": "MINISTERE DE LA JUSTICE"}]})

    monkeypatch.setattr(collector_approch.requests, "get", fake_get)
    cache: dict = {}
    collector_approch.resolve_siren_name("110010014", cache=cache)
    collector_approch.resolve_siren_name("110010014", cache=cache)
    assert len(calls) == 1
