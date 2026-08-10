"""Synthèse IA des DCE — fournisseur configurable (Gemini par défaut, gratuit ;
Anthropic en option).

LIMITES À NE JAMAIS MASQUER À L'UTILISATEUR (cf. README) :
- Gemini free tier (Google AI Studio) : modèles Flash / Flash-Lite uniquement
  (pas de Pro). Quota constaté empiriquement (juillet 2026, clé Google AI
  Studio standard) : gemini-2.5-flash est plafonné à 20 requêtes/JOUR
  (quota "GenerateRequestsPerDayPerProjectPerModel-FreeTier"), pas juste un
  débit par minute — un 429 dans ce cas ne se résout PAS en attendant
  quelques secondes, il faut attendre le lendemain (reset ~minuit Pacifique)
  ou changer de modèle. gemini-2.5-flash-lite dispose d'un quota séparé et
  peut prendre le relais le même jour. Les quotas exacts peuvent varier
  selon le compte/projet — toujours vérifier sur https://ai.dev/rate-limit.
  Les données envoyées au free tier PEUVENT être utilisées par Google pour
  améliorer ses produits ; une clause EEE/UK/Suisse peut imposer le passage
  au tier payant pour un usage professionnel. Les DCE sont des documents
  publics, mais cet usage doit être validé côté conformité avant
  industrialisation pour un cabinet de conseil français.
- Vérifier l'id de modèle exact sur https://ai.google.dev/gemini-api/docs/models
  et sur https://docs.claude.com avant toute mise en production — les id
  peuvent évoluer.
- Aucune valeur n'est inventée : toute information absente du document est
  renvoyée "non précisé", jamais estimée.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import anthropic
from google import genai
from google.genai import types as genai_types
from google.genai.errors import APIError as GeminiAPIError
from google.genai.errors import ClientError as GeminiClientError

import config

logger = logging.getLogger(__name__)

SYNTHESIS_FIELDS = (
    "mission", "delai_livraison", "calendrier", "penalites",
    "presentiel_exige", "references_clients_exigees", "grille_notation",
    "montant_estime", "remarques",
)

SYSTEM_PROMPT = """Tu es un assistant d'analyse d'appels d'offres publics français pour une PME de conseil IT (CFConsulting).
Analyse STRICTEMENT le document de consultation (DCE) fourni et renvoie UNIQUEMENT un objet JSON valide avec exactement ces clés :
- mission : résumé factuel de la mission demandée (2-4 phrases)
- delai_livraison : délai ou durée d'exécution du marché
- calendrier : dates clés mentionnées (limite de remise des offres, démarrage, jalons)
- penalites : la clause de pénalités du CCAP, recopiée VERBATIM si elle existe. Si un CCAG est référencé (CCAG-TIC ou CCAG-PI), indique lequel EXACTEMENT tel qu'écrit dans le document, sans supposer de formule de calcul s'il n'est pas explicite.
- presentiel_exige : "oui", "non" ou "non précisé" selon que le document exige une présence physique sur site
- references_clients_exigees : références clients / expérience exigées dans les critères de sélection
- grille_notation : critères d'attribution et leur pondération si mentionnée
- montant_estime : montant du marché si mentionné dans le document
- remarques : tout élément notable non couvert ci-dessus

RÈGLE ABSOLUE : si une information n'est pas présente dans le document, indique "non précisé" pour ce champ. N'invente JAMAIS de valeur, n'estime JAMAIS un montant ou un délai qui ne serait pas écrit noir sur blanc dans le texte. Ne renvoie rien d'autre que l'objet JSON, sans texte avant ou après, sans balises markdown."""


class SynthesisError(Exception):
    """Erreur de synthèse (appel LLM, parsing de la réponse...)."""


class SynthesisResult:
    def __init__(self, data: dict, provider: str, raw_response: str | None = None):
        self.data = data
        self.provider = provider
        self.raw_response = raw_response

    def to_dict(self) -> dict:
        """Retourne les 9 champs attendus, 'non précisé' si absent de la
        réponse du modèle (ne jamais laisser une clé manquante)."""
        return {field: self.data.get(field) or "non précisé" for field in SYNTHESIS_FIELDS}


def _extract_json(text: str) -> dict:
    """Extrait un objet JSON depuis la réponse du LLM (tolère les balises
    markdown ```json ... ``` que certains modèles ajoutent malgré la
    consigne de ne renvoyer que le JSON)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise SynthesisError(f"Réponse LLM non-JSON : {exc}") from exc


# ---------------------------------------------------------------------------
# Provider Gemini (gratuit par défaut) — lit le PDF nativement
# ---------------------------------------------------------------------------

_RETRYABLE_GEMINI_CODES = (429, 500, 503)


def _synthesize_gemini(pdf_path: Path | None, text: str | None, max_retries: int = 5) -> str:
    """Appelle l'API Gemini. Envoie le PDF directement si fourni (lecture
    native par le modèle), sinon le texte déjà extrait. Gère avec backoff
    exponentiel : 429 (débit/quota limité du free tier — cf. limites
    documentées ci-dessus) et 500/503 (surcharge temporaire du service,
    indépendante du quota)."""
    if not config.GEMINI_API_KEY:
        raise SynthesisError("GEMINI_API_KEY manquant (voir .env.example)")

    client = genai.Client(api_key=config.GEMINI_API_KEY)

    contents: list[Any] = [SYSTEM_PROMPT]
    if pdf_path is not None:
        contents.append(genai_types.Part.from_bytes(data=pdf_path.read_bytes(), mime_type="application/pdf"))
    elif text:
        contents.append(text)
    else:
        raise SynthesisError("Aucun contenu à synthétiser (ni PDF ni texte)")

    delay = 2.0
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=contents,
                config=genai_types.GenerateContentConfig(temperature=0),
            )
            return response.text or ""
        except GeminiAPIError as exc:
            code = getattr(exc, "code", None)
            if code in _RETRYABLE_GEMINI_CODES and attempt < max_retries - 1:
                logger.warning("Gemini %s (retryable) — retry dans %.1fs", code, delay)
                time.sleep(delay)
                delay *= 2
                last_exc = exc
                continue
            raise SynthesisError(f"Erreur Gemini : {exc}") from exc

    raise SynthesisError(f"Gemini : échec après {max_retries} tentatives") from last_exc


# ---------------------------------------------------------------------------
# Provider Anthropic (option)
# ---------------------------------------------------------------------------

def _synthesize_anthropic(pdf_path: Path | None, text: str | None) -> str:
    """Appelle l'API Anthropic (Claude). Modèle par défaut : claude-haiku-4-5
    (rapide/économique, adapté à l'extraction structurée PDF/texte -> JSON).
    Le SDK gère automatiquement le retry/backoff sur 429/5xx."""
    if not config.ANTHROPIC_API_KEY:
        raise SynthesisError("ANTHROPIC_API_KEY manquant (voir .env.example)")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    content: list[dict] = []
    if pdf_path is not None:
        pdf_b64 = base64.standard_b64encode(pdf_path.read_bytes()).decode()
        content.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64},
        })
    elif text:
        content.append({"type": "text", "text": text})
    else:
        raise SynthesisError("Aucun contenu à synthétiser (ni PDF ni texte)")
    content.append({"type": "text", "text": "Analyse ce document et renvoie le JSON demandé."})

    try:
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2000,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIError as exc:
        raise SynthesisError(f"Erreur Anthropic : {exc}") from exc

    return "".join(block.text for block in response.content if block.type == "text")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def synthesize(
    pdf_path: Path | None = None,
    text: str | None = None,
    provider: str | None = None,
) -> SynthesisResult:
    """Produit une synthèse structurée d'un document DCE. `pdf_path` a la
    priorité (envoi natif du PDF, mode recommandé pour Gemini) ; sinon
    `text` (texte déjà extrait par extractor.py)."""
    provider = provider or config.LLM_PROVIDER

    if provider == "gemini":
        raw = _synthesize_gemini(pdf_path, text)
    elif provider == "anthropic":
        raw = _synthesize_anthropic(pdf_path, text)
    elif provider == "local":
        raise SynthesisError("Provider 'local' non implémenté — configurer 'gemini' ou 'anthropic'")
    else:
        raise SynthesisError(f"Provider LLM inconnu : {provider}")

    data = _extract_json(raw)
    return SynthesisResult(data, provider=provider, raw_response=raw)
