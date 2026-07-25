# -*- coding: utf-8 -*-
"""Tests de similarite.py — AUCUN appel réseau réel : Gemini est mocké
(_gemini_generate) et l'encodeur d'embeddings est factice (_get_encoder).
Ne consomme donc pas de quota Gemini et tourne sans sentence-transformers."""
import json
import os
import tempfile
import unittest

import similarite as S


# --- Fabriques d'offres -------------------------------------------------------
def offre(poste, mission="", texte=""):
    return {"poste": poste, "mission": mission, "texte": texte}


# --- Faux Gemini : compte les appels, enregistre les prompts ------------------
class FauxGemini:
    """Remplace _gemini_generate. `mode` pilote le comportement."""
    def __init__(self, mode="ok"):
        self.mode = mode
        self.appels = 0
        self.prompts = []

    def __call__(self, prompt):
        self.appels += 1
        self.prompts.append(prompt)
        n = prompt.count("### OFFRE")
        if self.mode == "malforme":
            return "ceci n'est pas du json { cassé"
        if self.mode == "malforme_puis_ok":
            if self.appels == 1:
                return "{pas du json"
            return self._json_ok(n)
        if self.mode == "429_puis_ok":               # quota principal -> lite OK
            if self.appels == 1:
                raise RuntimeError("429 You exceeded your current quota")
            return self._json_ok(n)
        if self.mode == "sdk_absent":
            raise RuntimeError("No module named 'google'")
        if self.mode == "quota":
            raise RuntimeError("429 quota exhausted")
        if self.mode == "fences":
            return "```json\n" + self._json_ok(n) + "\n```"
        return self._json_ok(n)

    @staticmethod
    def _json_ok(n):
        items = [{"id": i, "score_global": 80, "verdict": "CONVENABLE",
                  "pole_principal": "Salle des marchés", "raison": "ok"}
                 for i in range(n)]
        return json.dumps(items)


# --- Faux encodeur d'embeddings : vecteurs déterministes par mots-clés ---------
class FauxEncodeur:
    """encode(textes) -> vecteurs 2D. Aligne les textes 'métier CFConsulting'
    sur [1,0] et les textes techniques hors-sujet sur [0,1]."""
    POS = ("amoa", "pmo", "salle", "recette", "conduite", "cahier des charges",
           "specification", "gouvernance", "besoin")
    NEG = ("java", "e-commerce", "développeur", "developpeur", "backend", "devops")

    def encode(self, textes):
        out = []
        for t in textes:
            tl = t.lower()
            if any(k in tl for k in self.NEG):
                out.append([0.0, 1.0])
            elif any(k in tl for k in self.POS):
                out.append([1.0, 0.0])
            else:
                out.append([0.5, 0.5])
        return out


class BaseSim(unittest.TestCase):
    def setUp(self):
        # caches isolés (jamais les vrais fichiers)
        self.tmp = tempfile.mkdtemp()
        self._cache_orig = S.CACHE_GEMINI
        self._emb_orig = S.EMB_CACHE
        S.CACHE_GEMINI = os.path.join(self.tmp, "cache_gemini.json")
        S.EMB_CACHE = os.path.join(self.tmp, "emb.json")
        # réinitialise les globals mémorisés
        S._ENCODER = "?"
        S._AVERTI_EMB = False
        S._MODELE_ACTIF = None
        self._gen_orig = S._gemini_generate
        self._enc_orig = S._get_encoder

    def tearDown(self):
        S.CACHE_GEMINI = self._cache_orig
        S.EMB_CACHE = self._emb_orig
        S._gemini_generate = self._gen_orig
        S._get_encoder = self._enc_orig
        S._ENCODER = "?"


# ═══════════════════════════════════════════════════════════════════════════
#  PARSING
# ═══════════════════════════════════════════════════════════════════════════
class TestParsing(BaseSim):
    def test_parse_simple(self):
        d = S.parse_reponse('[{"id":0,"score_global":90,"verdict":"CONVENABLE"}]')
        self.assertEqual(d[0]["score_global"], 90)

    def test_parse_tolere_fences_json(self):
        d = S.parse_reponse('```json\n[{"id":0,"score_global":70}]\n```')
        self.assertEqual(d[0]["id"], 0)

    def test_parse_tolere_texte_autour(self):
        d = S.parse_reponse('Voici le résultat :\n[{"id":0,"score_global":55}]\nMerci.')
        self.assertEqual(d[0]["score_global"], 55)

    def test_parse_malforme_leve(self):
        with self.assertRaises(Exception):
            S.parse_reponse("désolé, je ne peux pas répondre en JSON")


# ═══════════════════════════════════════════════════════════════════════════
#  GEMINI (mocké) : lots, cache, robustesse
# ═══════════════════════════════════════════════════════════════════════════
class TestGemini(BaseSim):
    def test_juge_et_cache(self):
        faux = FauxGemini("ok")
        S._gemini_generate = faux
        offres = [offre(f"AMOA banque {i}", "mission") for i in range(3)]
        r1 = S.juge_gemini(offres, profil_txt="PROFIL")
        self.assertEqual(len(r1), 3)
        self.assertEqual(r1[0]["verdict_gemini"], "CONVENABLE")
        self.assertEqual(faux.appels, 1)                 # 3 offres = 1 lot
        # 2e passage : tout est en cache -> AUCUN nouvel appel réseau
        r2 = S.juge_gemini(offres, profil_txt="PROFIL")
        self.assertEqual(faux.appels, 1)
        self.assertEqual(r2[0]["score_global"], 80)

    def test_cache_partiel(self):
        faux = FauxGemini("ok")
        S._gemini_generate = faux
        S.juge_gemini([offre("AMOA A")], profil_txt="P")
        self.assertEqual(faux.appels, 1)
        # A est en cache, B est neuf -> 1 seul nouvel appel, pour B
        S.juge_gemini([offre("AMOA A"), offre("PMO B")], profil_txt="P")
        self.assertEqual(faux.appels, 2)

    def test_lots_de_dix(self):
        faux = FauxGemini("ok")
        S._gemini_generate = faux
        S.GEMINI_DELAI = 0
        offres = [offre(f"AMOA {i}") for i in range(25)]
        r = S.juge_gemini(offres, profil_txt="P")
        self.assertEqual(len(r), 25)
        self.assertEqual(faux.appels, 3)                 # 10 + 10 + 5

    def test_retry_sur_json_malforme(self):
        faux = FauxGemini("malforme_puis_ok")
        S._gemini_generate = faux
        r = S.juge_gemini([offre("AMOA banque")], profil_txt="P")
        self.assertEqual(faux.appels, 2)                 # 1 raté + 1 ok
        self.assertEqual(r[0]["verdict_gemini"], "CONVENABLE")

    def test_json_malforme_persistant_marque_a_verifier(self):
        faux = FauxGemini("malforme")
        S._gemini_generate = faux
        r = S.juge_gemini([offre("AMOA banque")], profil_txt="P")
        self.assertTrue(r[0]["verdict_gemini"].startswith("A_VERIFIER"))
        # une offre non jugée n'est PAS mise en cache
        self.assertFalse(os.path.exists(S.CACHE_GEMINI) and
                         json.load(open(S.CACHE_GEMINI)))

    def test_bascule_modele_lite_sur_quota(self):
        """Quota du modèle principal épuisé (429) -> bascule sur le modèle lite
        et poursuit, au lieu de tomber en indisponible (choix 2026-07-22)."""
        S._gemini_generate = self._gen_orig      # vrai _gemini_generate ? non : on mocke
        faux = FauxGemini("429_puis_ok")
        S._gemini_generate = faux
        r = S.juge_gemini([offre("AMOA banque")], profil_txt="P")
        self.assertEqual(r[0]["verdict_gemini"], "CONVENABLE")   # lite a répondu
        self.assertEqual(S._MODELE_ACTIF, S.GEMINI_MODEL_LITE)   # bascule effectuée
        self.assertEqual(faux.appels, 2)                         # flash (429) + lite (ok)

    def test_sdk_absent_ne_plante_pas(self):
        faux = FauxGemini("sdk_absent")
        S._gemini_generate = faux
        r = S.juge_gemini([offre("AMOA banque")], profil_txt="P")
        self.assertEqual(r[0]["verdict_gemini"], "A_VERIFIER (Gemini indisponible)")


# ═══════════════════════════════════════════════════════════════════════════
#  DÉGRADATION & PRÉ-FILTRE EMBEDDINGS
# ═══════════════════════════════════════════════════════════════════════════
class TestEmbeddings(BaseSim):
    def test_use_embeddings_false_tout_a_gemini(self):
        faux = FauxGemini("ok")
        S._gemini_generate = faux
        # si _get_encoder était appelé, il planterait le test : on vérifie qu'il
        # ne l'est pas quand use_embeddings=False
        S._get_encoder = lambda: (_ for _ in ()).throw(AssertionError("ne doit pas être appelé"))
        r = S.similarite([offre("AMOA A"), offre("PMO B")], use_embeddings=False)
        self.assertEqual(faux.appels, 1)
        self.assertEqual(len(r), 2)
        self.assertIsNone(r[0]["score_semantique"])

    def test_encodeur_absent_tout_passe(self):
        faux = FauxGemini("ok")
        S._gemini_generate = faux
        S._get_encoder = lambda: None                    # sentence-transformers "absent"
        r = S.similarite([offre("Développeur Java e-commerce")], use_embeddings=True)
        self.assertEqual(faux.appels, 1)                 # rien coupé -> tout à Gemini
        self.assertEqual(r[0]["verdict_gemini"], "CONVENABLE")

    def test_prefiltre_coupe_hors_sujet_avant_gemini(self):
        faux = FauxGemini("ok")
        S._gemini_generate = faux
        S._get_encoder = lambda: FauxEncodeur()
        java = offre("Développeur Java e-commerce", "backend microservices")
        amoa = offre("AMOA salle des marchés", "cadrage recette conduite du changement")
        r = S.similarite([java, amoa], use_embeddings=True)
        # 1) le dev Java est coupé à l'étage 1, score < seuil
        self.assertEqual(r[0]["verdict_gemini"], "HORS_PERIMETRE")
        self.assertLess(r[0]["score_semantique"], S.EMB_SEUIL_PREFILTRE)
        # 2) il n'a JAMAIS atteint Gemini
        for p in faux.prompts:
            self.assertNotIn("Développeur Java", p)
        # 3) l'offre AMOA, elle, est bien allée à Gemini
        self.assertEqual(faux.appels, 1)
        self.assertTrue(any("AMOA salle des marchés" in p for p in faux.prompts))
        self.assertGreaterEqual(r[1]["score_semantique"], S.EMB_SEUIL_PREFILTRE)

    def test_repli_lexical_si_gemini_indisponible(self):
        """Gemini KO + embeddings absents -> le LEXICAL prend le relais : l'offre
        garde un score estimé (pour la prioriser) et reste 'à vérifier'."""
        S._gemini_generate = FauxGemini("sdk_absent")
        S._get_encoder = lambda: None
        r = S.similarite([offre("AMOA banque", "cahier des charges recette conduite du changement")],
                         use_embeddings=True)
        self.assertTrue(r[0].get("estime"))
        self.assertEqual(S.verdict_similarite(r[0]), "À VÉRIFIER (estimé sans Gemini)")
        self.assertIsInstance(r[0]["score_global"], int)     # score de repli présent
        self.assertGreater(r[0]["score_global"], 0)

    def test_repli_embeddings_si_gemini_indisponible(self):
        """Gemini KO + embeddings DISPO -> le sémantique prend le relais
        (meilleur que le lexical) pour récupérer au mieux les offres proches."""
        S._gemini_generate = FauxGemini("quota")             # échoue (429)
        S._get_encoder = lambda: FauxEncodeur()
        S.GEMINI_BACKOFF = 0
        amoa = offre("AMOA salle des marchés", "cadrage recette conduite du changement")
        r = S.similarite([amoa], use_embeddings=True)
        self.assertTrue(r[0].get("estime"))
        self.assertEqual(r[0]["score_global"], r[0]["score_semantique"])  # repli = embeddings
        self.assertEqual(S.verdict_similarite(r[0]), "À VÉRIFIER (estimé sans Gemini)")

    def test_score_lexical_present(self):
        faux = FauxGemini("ok")
        S._gemini_generate = faux
        S._get_encoder = lambda: None
        r = S.similarite([offre("AMOA banque", "cahier des charges recette")],
                         use_embeddings=True)
        self.assertIsInstance(r[0]["score_lexical"], int)
        self.assertGreater(r[0]["score_lexical"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
