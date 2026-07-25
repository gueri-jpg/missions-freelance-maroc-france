# -*- coding: utf-8 -*-
"""Filtre de SIMILARITÉ en cascade (au-dessus des 4 filtres binaires existants).

Objectif : ne garder que les offres qui ressemblent, DANS LEUR GLOBALITÉ, à ce
que CFConsulting sait faire — pas juste par mots-clés. Deux étages, du moins
cher au plus intelligent :

  Étage 1  embeddings locaux (pré-filtre, GRATUIT, optionnel)  -> pre_filtre_semantique
           videur permissif : jette ce qui est franchement hors-sujet, en cas
           de doute LAISSE PASSER vers Gemini.
  Étage 2  Gemini (juge final)                                 -> juge_gemini
           lit l'annonce entière, rend score + verdict + pôle + raison.

Contraintes tenues :
  * module PUR et testable ; le SEUL point réseau est `_gemini_generate()`
    (mocké dans les tests) ; l'encodeur passe par `_get_encoder()` (mockable).
  * clé Gemini uniquement via os.environ["GEMINI_API_KEY"], jamais logguée.
  * dégrade sans planter : sentence-transformers absent / SDK absent / clé
    absente / quota 429 -> on marque "A_VERIFIER (...)", jamais de crash.
  * cache (cache_gemini.json) : une annonce déjà jugée n'est jamais re-payée.
"""
import hashlib
import json
import os
import re
import time

import score_competences as _sc

OUTDIR = os.path.dirname(os.path.abspath(__file__))

# --- Config (surchargeable par variables d'environnement) --------------------
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
# Modèle de REPLI : quand le quota du modèle principal est épuisé (429), on
# bascule sur le lite (quota journalier 4× plus large) pour finir le run au lieu
# de tomber sur l'estimation embeddings. Choix utilisatrice 2026-07-22.
GEMINI_MODEL_LITE = os.environ.get("GEMINI_MODEL_LITE", "gemini-2.5-flash-lite")
_MODELE_ACTIF = None       # modèle réellement utilisé (bascule flash -> lite)
USE_EMBEDDINGS = os.environ.get("USE_EMBEDDINGS", "1") != "0"
EMB_MODEL_NOM = os.environ.get("EMB_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
# Seuil du pré-filtre embeddings : TRÈS permissif (rôle de simple videur). Calé
# à 35 le 2026-07-22 après mesure sur les offres réelles curées par
# l'utilisatrice (jaunes + "À POSTULER") : le modèle multilingue donne des
# scores bas (bonnes offres 39-62, hors-sujet 32-35) -> à 45 on coupait des
# offres notées 90-100 par Gemini. À 35 : on ne coupe que le hors-sujet franc
# (< 35), aucune bonne offre perdue, et Gemini tranche le reste.
EMB_SEUIL_PREFILTRE = int(os.environ.get("EMB_SEUIL_PREFILTRE", "35"))
GEMINI_BATCH = int(os.environ.get("GEMINI_BATCH", "10"))
GEMINI_DELAI = float(os.environ.get("GEMINI_DELAI", "1.0"))     # pause entre lots
GEMINI_BACKOFF = float(os.environ.get("GEMINI_BACKOFF", "20.0"))  # pause sur 429

# Seuils de décision (calibrés le 2026-07-22 sur le fichier trié : bonnes offres
# médiane 90, technique/hors-secteur 0-45, zone limite 50-70). Réglage STRICT
# demandé par l'utilisatrice ("très similaires, pas de faux positifs").
SIM_SEUIL_HAUT = int(os.environ.get("SIM_SEUIL_HAUT", "75"))   # >= -> CONVENABLE
SIM_SEUIL_BAS = int(os.environ.get("SIM_SEUIL_BAS", "55"))     # < -> écartée

PROFIL_PATH = os.path.join(OUTDIR, "profil_ideal.txt")
CACHE_GEMINI = os.path.join(OUTDIR, "cache_gemini.json")
EMB_CACHE = os.path.join(OUTDIR, ".cache_embeddings_ideal.pt")

# Contre-exemples : ce qui N'EST PAS pour CFConsulting (cadre le jugement Gemini).
CONTRE_EXEMPLES = [
    "cybersécurité pure (pilotage ou expertise sécurité), même en banque",
    "développement backend / devops / intégration technique sans dimension "
    "fonctionnelle (AMOA/MOA)",
    "poste en CDI interne d'une banque cliente (recrutement pour son effectif)",
    "infogérance, support N1/N2, exploitation, run applicatif",
    "vente/édition d'un progiciel en tant qu'éditeur du logiciel",
    "missions hors du secteur banque / finance / assurance",
]

_AVERTI_EMB = False       # pour n'avertir qu'une fois de l'absence d'embeddings


# ═══════════════════════════════════════════════════════════════════════════
#  PROFIL IDÉAL
# ═══════════════════════════════════════════════════════════════════════════
def charger_profil(path=PROFIL_PATH):
    """Renvoie (blocs_positifs, texte_complet).

    - blocs_positifs : les blocs de SAVOIR-FAIRE (hors bloc PÔLES) -> embeddings.
    - texte_complet  : tout le profil (positifs + pôles) -> prompt Gemini.
    Un bloc = un paragraphe séparé par une ligne vide ; les lignes '#' ignorées.
    """
    try:
        with open(path, encoding="utf-8") as f:
            brut = f.read()
    except FileNotFoundError:
        return [], ""
    lignes = [l for l in brut.splitlines() if not l.lstrip().startswith("#")]
    blocs = [b.strip() for b in re.split(r"\n\s*\n", "\n".join(lignes)) if b.strip()]
    positifs = [b for b in blocs if not b.upper().startswith("PÔLES")
                and not b.upper().startswith("POLES")]
    return positifs, "\n\n".join(blocs)


# ═══════════════════════════════════════════════════════════════════════════
#  OUTILS
# ═══════════════════════════════════════════════════════════════════════════
def _titre(offre):
    return str(offre.get("poste", "") or "").strip()


def _mission(offre):
    return str(offre.get("mission", "") or "").strip()


def _texte_complet(offre):
    """Texte pour Gemini : titre + mission + description complète."""
    parts = [_titre(offre), _mission(offre), str(offre.get("texte", "") or "")]
    return "\n".join(p for p in parts if p).strip()


def _texte_court(offre):
    """Texte pour les embeddings : titre + mission (cf. spec)."""
    return (_titre(offre) + " " + _mission(offre)).strip()


def _cle(offre):
    """Clé de cache = hash de (titre + mission), stable et insensible à la casse."""
    base = (_titre(offre) + "||" + _mission(offre)).lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def _score_lexical(offre):
    """Réutilise score_competences.py (indicatif, non décisionnel)."""
    blob = _sc.norm(_titre(offre) + " " + _texte_complet(offre))
    total, _ = _sc.score_competences(blob)
    return total


def _charger_cache():
    try:
        with open(CACHE_GEMINI, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _sauver_cache(cache):
    tmp = CACHE_GEMINI + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CACHE_GEMINI)


# ═══════════════════════════════════════════════════════════════════════════
#  ÉTAGE 1 — EMBEDDINGS (pré-filtre)
# ═══════════════════════════════════════════════════════════════════════════
_ENCODER = "?"     # sentinelle : "?" = pas encore tenté


def _get_encoder():
    """Charge SentenceTransformer une fois. Renvoie None si la lib est absente
    (le pipeline saute alors l'étage 1). Mockable dans les tests."""
    global _ENCODER
    if _ENCODER != "?":
        return _ENCODER
    try:
        from sentence_transformers import SentenceTransformer
        _ENCODER = SentenceTransformer(EMB_MODEL_NOM)
    except Exception:
        _ENCODER = None
    return _ENCODER


def _cos(u, v):
    """Cosinus en Python pur (pas de numpy)."""
    ps = sum(a * b for a, b in zip(u, v))
    nu = sum(a * a for a in u) ** 0.5
    nv = sum(b * b for b in v) ** 0.5
    if nu == 0 or nv == 0:
        return 0.0
    return ps / (nu * nv)


def _vect(encoder, textes):
    """Encode une liste de textes -> liste de vecteurs (listes de floats)."""
    arr = encoder.encode(textes)
    out = []
    for v in arr:
        out.append(list(v.tolist()) if hasattr(v, "tolist") else list(v))
    return out


def _embeddings_ideal(encoder, blocs):
    """Vecteurs des blocs de profil, mis en cache disque (recalcul si le profil
    change : la clé inclut le nombre de blocs et un hash de leur contenu)."""
    sig = hashlib.sha1(("||".join(blocs)).encode("utf-8")).hexdigest()[:12]
    try:
        with open(EMB_CACHE, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("sig") == sig and d.get("modele") == EMB_MODEL_NOM:
            return d["vecteurs"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    vecteurs = _vect(encoder, blocs)
    try:
        with open(EMB_CACHE, "w", encoding="utf-8") as f:
            json.dump({"sig": sig, "modele": EMB_MODEL_NOM, "vecteurs": vecteurs}, f)
    except OSError:
        pass
    return vecteurs


def pre_filtre_semantique(offres, seuil=None, blocs=None):
    """Étage 1. Renvoie {index_offre -> score_semantique(0-100)}.

    - score = 100 * max(cosinus(titre+mission, bloc)) sur les blocs positifs.
    - Si l'encodeur est absent : renvoie {} et n'avertit qu'une fois -> l'appelant
      considère alors que TOUT passe (aucun pré-filtre). Jamais de crash.
    - Rôle de VIDEUR permissif : `seuil` bas ; en cas de doute on laisse passer.
    """
    global _AVERTI_EMB
    if seuil is None:
        seuil = EMB_SEUIL_PREFILTRE
    encoder = _get_encoder()
    if encoder is None:
        if not _AVERTI_EMB:
            print("  [similarité] sentence-transformers absent -> étage 1 sauté, "
                  "tout va vers Gemini.")
            _AVERTI_EMB = True
        return {}
    if blocs is None:
        blocs, _ = charger_profil()
    if not blocs:
        return {}
    vb = _embeddings_ideal(encoder, blocs)
    textes = [_texte_court(o) for o in offres]
    vo = _vect(encoder, textes)
    scores = {}
    for i, v in enumerate(vo):
        best = max((_cos(v, b) for b in vb), default=0.0)
        scores[i] = round(max(0.0, best) * 100)
    return scores


# ═══════════════════════════════════════════════════════════════════════════
#  ÉTAGE 2 — GEMINI (juge final)
# ═══════════════════════════════════════════════════════════════════════════
def _gemini_generate(prompt):
    """SEUL point réseau. Lève une exception si SDK/clé absents ou erreur API.
    La clé n'est JAMAIS logguée. Mocké dans les tests.

    Compatible avec les DEUX SDK Google : le nouveau `google-genai` (préféré)
    et l'ancien `google-generativeai` (déprécié mais encore fonctionnel)."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY non définie")
    modele = _MODELE_ACTIF or GEMINI_MODEL
    try:                                          # SDK récent : google-genai
        from google import genai
        client = genai.Client(api_key=key)
        return client.models.generate_content(model=modele, contents=prompt).text
    except ImportError:
        pass
    import google.generativeai as genai           # repli : ancien SDK
    genai.configure(api_key=key)
    return genai.GenerativeModel(modele).generate_content(prompt).text


def construire_prompt(lot, profil_txt):
    """Prompt strict FR : profil + pôles + contre-exemples + offres numérotées,
    réponse JSON uniquement."""
    contre = "\n".join(f"- {c}" for c in CONTRE_EXEMPLES)
    blocs_offres = []
    for i, o in enumerate(lot):
        txt = _texte_complet(o)
        if len(txt) > 3500:
            txt = txt[:3500] + " […]"
        blocs_offres.append(f"### OFFRE {i}\nTitre : {_titre(o)}\nAnnonce :\n{txt}")
    offres_txt = "\n\n".join(blocs_offres)
    return f"""Tu évalues si des missions IT correspondent au savoir-faire du cabinet CFConsulting, qui place des consultants en régie/freelance dans la BANQUE.

=== CE QUE CFCONSULTING SAIT FAIRE (profil idéal + pôles métier valides) ===
{profil_txt}

=== CE QUI N'EST PAS POUR CFCONSULTING (contre-exemples) ===
{contre}

=== RÈGLES DE JUGEMENT (à respecter strictement) ===
1. Juge la SIMILARITÉ DE FOND : le métier réellement demandé par la mission comparé à ce que CFConsulting sait faire (AMOA/MOA, PMO, cadrage, expression de besoin, spécifications, recette, conduite du changement, pilotage, gouvernance, BI fonctionnelle). NE te fie PAS à la simple présence de mots bancaires.
1bis. RÈGLE DE MATCH POSITIF : si l'offre relève d'un des PÔLES VALIDES ET qu'elle demande une ou plusieurs des COMPÉTENCES du profil idéal ci-dessus (AMOA / expression de besoin, cahier des charges / spécifications fonctionnelles, ateliers métiers, recette / tests, conduite du changement, RACI, pilotage / PMO, gouvernance / COPIL, tableaux de bord BI fonctionnels), alors elle est CONVENABLE et doit recevoir un SCORE ÉLEVÉ (≥ 75) — même si elle n'est pas identique à l'offre de référence. Le profil idéal et l'offre de référence sont des EXEMPLES du savoir-faire, pas une liste fermée : toute mission fonctionnelle de ce type, dans un pôle valide, correspond.
2. Une mission "cybersécurité en banque", "développeur backend en banque", "data engineer / data scientist", "support/run en banque" ou "intégration technique / architecture technique" doit scorer BAS malgré le vocabulaire bancaire : le métier n'est pas le nôtre (technique, pas fonctionnel AMOA/MOA).
3. SECTEUR : le CLIENT FINAL de la mission doit RÉELLEMENT opérer dans la banque / finance / assurance, ET le sujet doit relever d'un des pôles valides. Une simple mention du mot "banque" ne suffit PAS : si le client est du retail, de l'industrie, de l'automobile, des télécoms, du secteur "Autre" ou public, ou si le secteur n'est pas explicitement bancaire/financier, scorer BAS (HORS_PERIMETRE).
4. Sois factuel et concis, jamais flatteur. En cas de doute sérieux sur le secteur ou sur la nature fonctionnelle du métier, penche vers un score BAS (priorité : zéro faux positif).

=== OFFRES À ÉVALUER ===
{offres_txt}

=== FORMAT DE RÉPONSE ===
Réponds UNIQUEMENT par un tableau JSON (aucun texte avant ou après), un objet par offre, dans l'ordre :
[{{"id": <int, le numéro de l'offre>, "score_global": <entier 0-100>, "verdict": "CONVENABLE"|"LIMITE"|"HORS_PERIMETRE", "pole_principal": "<un des pôles valides, ou '-'>", "raison": "<une seule phrase courte et factuelle>"}}]"""


def parse_reponse(txt):
    """Parse tolérant : retire d'éventuelles clôtures ```json ``` et tout texte
    autour, renvoie la liste d'objets. Lève ValueError si rien d'exploitable."""
    if not txt:
        raise ValueError("réponse vide")
    s = txt.strip()
    s = re.sub(r"^```(?:json)?", "", s.strip()).strip()
    s = re.sub(r"```$", "", s.strip()).strip()
    # isole le premier tableau JSON s'il y a du bruit autour
    i, j = s.find("["), s.rfind("]")
    if i != -1 and j != -1 and j > i:
        s = s[i:j + 1]
    data = json.loads(s)
    if not isinstance(data, list):
        raise ValueError("le JSON n'est pas une liste")
    return data


def _normaliser_item(item):
    """Normalise un objet Gemini en champs sûrs."""
    verdict = str(item.get("verdict", "")).upper().strip()
    if verdict not in ("CONVENABLE", "LIMITE", "HORS_PERIMETRE"):
        verdict = "LIMITE"
    try:
        score = int(round(float(item.get("score_global", 0))))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))
    return {
        "score_global": score,
        "verdict_gemini": verdict,
        "pole_principal": str(item.get("pole_principal", "-") or "-").strip(),
        "raison": str(item.get("raison", "") or "").strip(),
    }


def _juger_lot(lot, profil_txt):
    """Juge un lot d'offres. Renvoie une liste alignée sur `lot`. Robuste :
    bascule sur le modèle lite au 429, re-tente une fois sur JSON malformé,
    backoff sur quota, ne plante jamais."""
    global _MODELE_ACTIF
    if _MODELE_ACTIF is None:
        _MODELE_ACTIF = GEMINI_MODEL
    prompt = construire_prompt(lot, profil_txt)
    derniere_err = ""
    essais_json = 0
    for _ in range(4):        # marge : bascule modèle + 1 retry JSON + backoff
        try:
            brut = _gemini_generate(prompt)
        except Exception as e:                       # SDK/clé/API
            msg = str(e)
            derniere_err = msg
            if any(k in msg.lower() for k in ("429", "quota", "rate", "exhaust")):
                # quota épuisé : on bascule d'abord sur le modèle lite, et
                # seulement si le lite est AUSSI épuisé on fait un backoff.
                if _MODELE_ACTIF != GEMINI_MODEL_LITE:
                    print(f"  [similarité] quota {_MODELE_ACTIF} épuisé -> "
                          f"bascule sur {GEMINI_MODEL_LITE}")
                    _MODELE_ACTIF = GEMINI_MODEL_LITE
                    continue
                time.sleep(GEMINI_BACKOFF)
                continue
            # SDK/clé absents : inutile de re-tenter
            return [_indispo(o, msg) for o in lot]
        try:
            data = parse_reponse(brut)
        except Exception as e:
            derniere_err = f"JSON: {e}"
            essais_json += 1
            if essais_json <= 1:
                continue                              # re-tente une fois
            break
        # mappe par 'id' quand présent, sinon par position
        par_id = {}
        for it in data:
            if isinstance(it, dict) and "id" in it:
                try:
                    par_id[int(it["id"])] = it
                except (TypeError, ValueError):
                    pass
        out = []
        for i, o in enumerate(lot):
            it = par_id.get(i) or (data[i] if i < len(data) and isinstance(data[i], dict) else None)
            out.append(_normaliser_item(it) if it else _erreur(o, "réponse partielle"))
        return out
    # deux tentatives ratées
    return [_erreur(o, derniere_err or "réponse illisible") for o in lot]


def _erreur(offre, msg=""):
    return {"score_global": None, "verdict_gemini": "A_VERIFIER (erreur Gemini)",
            "pole_principal": "-", "raison": ("Gemini: " + msg)[:160]}


def _indispo(offre, msg=""):
    return {"score_global": None, "verdict_gemini": "A_VERIFIER (Gemini indisponible)",
            "pole_principal": "-", "raison": ("Gemini indisponible: " + msg)[:160]}


def juge_gemini(offres, profil_txt=None):
    """Étage 2. Renvoie une liste (alignée sur `offres`) de dicts Gemini.
    N'appelle Gemini QUE sur les offres absentes du cache (cache_gemini.json).
    Traite par lots de GEMINI_BATCH. Ne plante jamais."""
    if profil_txt is None:
        _, profil_txt = charger_profil()
    cache = _charger_cache()
    resultats = [None] * len(offres)
    a_juger = []                                     # (index, offre)
    for i, o in enumerate(offres):
        c = cache.get(_cle(o))
        if c is not None:
            resultats[i] = dict(c)
        else:
            a_juger.append((i, o))

    modifie = False
    for depart in range(0, len(a_juger), GEMINI_BATCH):
        tranche = a_juger[depart:depart + GEMINI_BATCH]
        lot = [o for _, o in tranche]
        juges = _juger_lot(lot, profil_txt)
        for (i, o), res in zip(tranche, juges):
            resultats[i] = res
            # on ne met en cache QUE les jugements aboutis (pas les "A_VERIFIER")
            if not str(res["verdict_gemini"]).startswith("A_VERIFIER"):
                cache[_cle(o)] = res
                modifie = True
        if depart + GEMINI_BATCH < len(a_juger):
            time.sleep(GEMINI_DELAI)

    if modifie:
        try:
            _sauver_cache(cache)
        except OSError:
            pass
    return resultats


# ═══════════════════════════════════════════════════════════════════════════
#  ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════
def _lexical_100(lex):
    """Convertit le score lexical (0..~17, cf. score_competences) en 0-100."""
    if lex is None:
        return 0
    return min(100, round(lex / 17.0 * 100))


def verdict_similarite(res):
    """Traduit un résultat de similarité (dict) en décision, selon les seuils.

    Renvoie l'une des valeurs :
      "CONVENABLE"                     score >= SIM_SEUIL_HAUT (gardée d'office)
      "À VÉRIFIER (similarité)"        SIM_SEUIL_BAS <= score < SIM_SEUIL_HAUT
      "HORS_PERIMETRE (similarité)"    score < SIM_SEUIL_BAS (à écarter des NOUVELLES)
      "À VÉRIFIER (estimé sans Gemini)" score de REPLI (embeddings/lexical) quand
          Gemini est indisponible : on NE hard-exclut JAMAIS sur une estimation,
          l'offre est gardée à vérifier (avec un score pour la prioriser).
    """
    if res.get("estime"):
        return "À VÉRIFIER (estimé sans Gemini)"
    s = res.get("score_global")
    if s is None:
        return "À VÉRIFIER (Gemini indisponible)"
    if s >= SIM_SEUIL_HAUT:
        return "CONVENABLE"
    if s >= SIM_SEUIL_BAS:
        return "À VÉRIFIER (similarité)"
    return "HORS_PERIMETRE (similarité)"


def similarite(offres, use_embeddings=True):
    """Applique l'étage 1 (si activé + lib présente) puis l'étage 2, et renvoie
    une liste alignée sur `offres` :
      {score_global, verdict_gemini, pole_principal, raison,
       score_semantique, score_lexical}

    - Étage 1 coupe les offres franchement hors-sujet (score_semantique < seuil)
      AVANT Gemini : elles reçoivent verdict "HORS_PERIMETRE" sans appel payant.
    - En cas de doute (>= seuil, ou encodeur absent) : on laisse passer à Gemini.
    """
    n = len(offres)
    score_lex = [_score_lexical(o) for o in offres]
    score_sem = [None] * n

    if use_embeddings and USE_EMBEDDINGS:
        sem = pre_filtre_semantique(offres)          # {} si encodeur absent
        for i, s in sem.items():
            score_sem[i] = s

    # Étage 1 : qui va à Gemini, qui est coupé ? On NE coupe QUE les offres pas
    # encore jugées : une annonce déjà en cache Gemini garde son vrai verdict
    # (le pré-filtre ne sert qu'à éviter des appels sur les NOUVELLES offres).
    cache = _charger_cache()
    a_gemini_idx, coupe = [], {}
    for i in range(n):
        s = score_sem[i]
        deja_juge = _cle(offres[i]) in cache
        if (not deja_juge) and s is not None and s < EMB_SEUIL_PREFILTRE:
            coupe[i] = {
                "score_global": s,
                "verdict_gemini": "HORS_PERIMETRE",
                "pole_principal": "-",
                "raison": f"Pré-filtre sémantique : hors-sujet (score {s} < "
                          f"{EMB_SEUIL_PREFILTRE}), non soumis à Gemini.",
            }
        else:
            a_gemini_idx.append(i)

    # Étage 2 : Gemini sur les survivants
    juges = juge_gemini([offres[i] for i in a_gemini_idx])
    par_idx = dict(zip(a_gemini_idx, juges))

    out = []
    for i in range(n):
        base = coupe.get(i) or par_idx[i]
        # REPLI si Gemini indisponible : les embeddings (si dispo) ou le lexical
        # estiment la similarité -> on récupère au mieux les offres proches, sans
        # jamais hard-exclure sur une estimation (l'offre reste "à vérifier").
        if (base.get("score_global") is None
                and str(base.get("verdict_gemini", "")).startswith("A_VERIFIER")):
            emb = score_sem[i]
            fb = emb if emb is not None else _lexical_100(score_lex[i])
            src = "embeddings" if emb is not None else "lexical"
            base = {**base, "score_global": fb, "estime": True,
                    "pole_principal": base.get("pole_principal", "-"),
                    "raison": f"Score ESTIMÉ sans Gemini ({src}) : {fb}/100 — "
                              f"à confirmer quand Gemini sera disponible."}
        out.append({**base, "score_semantique": score_sem[i],
                    "score_lexical": score_lex[i]})
    return out
