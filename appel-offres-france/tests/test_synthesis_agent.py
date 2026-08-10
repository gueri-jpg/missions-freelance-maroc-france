"""Tests de synthesis_agent.py — providers mockés (aucun appel réseau)."""
from __future__ import annotations

import json

import pytest

import config
import synthesis_agent
from synthesis_agent import SynthesisError, SynthesisResult, synthesize


class _FakeGeminiResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeGeminiModels:
    """Simule client.models.generate_content, avec un nombre configurable
    d'échecs 429 avant succès."""

    def __init__(self, fail_times: int, final_text: str):
        self.fail_times = fail_times
        self.final_text = final_text
        self.calls = 0

    def generate_content(self, model, contents, config):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise synthesis_agent.GeminiClientError(429, {"error": {"message": "rate limited"}})
        return _FakeGeminiResponse(self.final_text)


def _install_fake_gemini_client(monkeypatch, fail_times: int, final_text: str) -> _FakeGeminiModels:
    fake_models = _FakeGeminiModels(fail_times=fail_times, final_text=final_text)

    class FakeClient:
        def __init__(self, api_key):
            self.models = fake_models

    monkeypatch.setattr(synthesis_agent, "GEMINI_API_KEY_CHECK", True, raising=False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key-for-tests")
    monkeypatch.setattr(synthesis_agent.genai, "Client", FakeClient)
    monkeypatch.setattr(synthesis_agent.time, "sleep", lambda seconds: None)
    return fake_models


def test_gemini_mock_renvoie_un_json_valide(monkeypatch):
    valid_json = json.dumps({
        "mission": "Développement d'une application de gestion RH",
        "delai_livraison": "6 mois",
        "montant_estime": "80000",
    })
    fake_models = _install_fake_gemini_client(monkeypatch, fail_times=0, final_text=valid_json)

    result = synthesize(text="Texte du CCTP", provider="gemini")

    assert isinstance(result, SynthesisResult)
    assert result.provider == "gemini"
    assert result.data["mission"] == "Développement d'une application de gestion RH"
    assert fake_models.calls == 1


def test_gemini_gere_un_429_avec_retry(monkeypatch):
    valid_json = json.dumps({"mission": "Développement logiciel"})
    fake_models = _install_fake_gemini_client(monkeypatch, fail_times=2, final_text=valid_json)

    result = synthesize(text="Texte du CCTP", provider="gemini")

    assert result.data["mission"] == "Développement logiciel"
    assert fake_models.calls == 3  # 2 échecs 429 puis succès


def test_gemini_abandonne_apres_max_retries(monkeypatch):
    _install_fake_gemini_client(monkeypatch, fail_times=999, final_text="{}")

    with pytest.raises(SynthesisError):
        synthesize(text="Texte du CCTP", provider="gemini")


def test_gemini_sans_cle_api_leve_erreur_explicite(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(SynthesisError):
        synthesize(text="Texte du CCTP", provider="gemini")


def test_provider_inconnu_leve_erreur():
    with pytest.raises(SynthesisError):
        synthesize(text="Texte du CCTP", provider="openai-non-supporte")


def test_extract_json_tolere_balises_markdown():
    raw = '```json\n{"mission": "test"}\n```'
    data = synthesis_agent._extract_json(raw)
    assert data == {"mission": "test"}


def test_extract_json_leve_erreur_si_non_json():
    with pytest.raises(SynthesisError):
        synthesis_agent._extract_json("Ceci n'est pas du JSON")


def test_to_dict_renvoie_non_precise_pour_champs_absents():
    """Renvoie 'non précisé' pour toute information absente — jamais
    d'invention de valeur (règle d'exactitude)."""
    result = SynthesisResult(data={"mission": "Développement d'un site web"}, provider="gemini")
    d = result.to_dict()

    assert d["mission"] == "Développement d'un site web"
    assert d["penalites"] == "non précisé"
    assert d["montant_estime"] == "non précisé"
    assert d["calendrier"] == "non précisé"
    assert set(d.keys()) == set(synthesis_agent.SYNTHESIS_FIELDS)


def test_to_dict_toutes_les_cles_absentes():
    result = SynthesisResult(data={}, provider="anthropic")
    d = result.to_dict()
    assert all(v == "non précisé" for v in d.values())
