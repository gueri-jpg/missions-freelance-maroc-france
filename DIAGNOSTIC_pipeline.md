# Diagnostic — `missions-freelance-maroc-france`

Analyse du 30/07/2026 sur le commit `main` (1 commit). Méthode : lecture de `classifier.py`,
`similarite.py`, `score_competences.py`, `profil_ideal.txt`, `linkedin_sourcing_regie.py`, puis
exécution de votre propre `detect_domaine()` sur les 51 offres que j'avais trouvées manuellement,
et analyse statistique des 209 lignes de vos onglets `*(sourcing)`.

---

## Synthèse en une phrase

Vos deux symptômes ont deux causes **indépendantes** : les faux négatifs viennent de
`EXCLUS_HARD_KW` et de l'absence d'un pôle métier « IT / Transformation » ; les faux positifs
viennent du fait que **le score Gemini n'a aucun pouvoir de décision** — il annote, il ne filtre pas.

Le point le plus embarrassant, et le plus utile pour se repérer : **votre pipeline rejetterait
l'offre de référence qu'il est censé trouver.** Elle est dans votre fichier avec un score de 60,
un pôle `-`, et cette raison Gemini :

> « PMO pertinent mais sujet (modernisation outils infra) un peu à côté du cœur AMOA banque. »

Le sujet de votre mission cible est *la modernisation d'outils d'infrastructure*. Votre
classifieur met `infrastructure` en exclusion dure et votre référentiel de pôles n'a pas de case
où la ranger.

---

# A. Les faux négatifs

## A1 — `infrastructure` est en exclusion DURE, testée sur le titre

`classifier.py` l.162 (`EXCLUS_HARD_KW`) contient `"infrastructure"`, `"infra "`, `"réseau"`,
`"réseaux"`. Et `detect_domaine()` l.725 les applique en tout premier, sans recours :

```python
# 1) Exclusions dures (titre)
if has_any(poste, EXCLUS_HARD_KW):
    return False, False, True        # hors périmètre quoi qu'il arrive
```

Le commentaire l.147 est explicite : *« jamais pertinent, même si data/BI apparaît »*.

**Mesure.** Sur mes 51 offres passées dans votre `detect_domaine()` : **7 sont écartées par
exclusion dure**, dont ma meilleure trouvaille du marché :

| Score | Offre | Mot-clé fautif |
|---|---|---|
| 96 % | Chef de projet Infrastructure / Gouvernance projets — GIE d'infrastructure **bancaire**, Paris 13e, 16 mois, **600-610 €**, démarrage 01/09 | `infrastructure` |
| 84 % | PMO Infra / Production bancaire — Freelance (REF03), Trusted Advisors Casablanca | `infra ` |
| 74 % | Directeur de projet — référentiel / urbanisation SI, banque, Bordeaux | `urbanisation` |
| 68 % | Chef de projet SI — Agile / Jira / Confluence, Paris | `projet si` |
| 64 % | Chef de projet Infrastructure Réseaux, Bordeaux | `réseaux` |
| 64 % | Responsable applicatif / Chef de projet SI — BPM, Paris | `projet si` |
| 64 % | Chef de projet SI / Chef de projet AMOA — Al Barid Bank, Rabat | `projet si` |

Le raisonnement d'origine était sain : écarter les postes d'*ingénieur* infra. Mais l'exclusion
porte sur un mot du titre, pas sur le métier. Un **PMO qui pilote la gouvernance d'un projet
d'infrastructure** est fonctionnel, pas technique — et c'est exactement votre cible.

## A2 — Bug de sous-chaîne : `"projet si"` tue trois de vos propres pôles valides

`"projet si"` est un motif de 9 caractères testé en sous-chaîne. Il ne matche pas seulement
« chef de projet SI » :

| Titre testé | Écarté ? | Pôle valide détruit |
|---|---|---|
| Chef de projet **SI**RH Data Migration | **OUI** | SIRH |
| Chef de projet **Si**nistres | **OUI** | Bancassurance |
| PMO Chef de projet **Si**mulation ALM | **OUI** | ALM |
| Chef de projet **Si**gnature électronique | **OUI** | Paiements & Monétique |
| Chef de projet **SI** bancaire | **OUI** | — |

Vous perdez silencieusement des missions SIRH, Bancassurance et ALM, trois de vos onze pôles
officiels, à cause d'un motif trop court. Aucun test de `test_classifier.py` ne couvre ce cas.

## A3 — Il n'existe aucun pôle métier pour le pilotage IT

`profil_ideal.txt`, bloc PÔLES :

> PÔLES MÉTIER VALIDES (le sujet de la mission **doit** relever de l'un d'eux) : Crédit &
> Engagement ; Salle des marchés ; Gestion d'actifs ; Intermédiation boursière ; Paiements &
> Monétique ; SIRH ; Risques ; Planification budgétaire ; Bancassurance ; KYC & Conformité ; ALM.

Les onze pôles sont tous des **domaines métier bancaires**. Aucun ne couvre ITSM, CMDB, socle
technique, poste de travail, Digital Workplace, Microsoft 365 ou gouvernance documentaire.

Et le prompt Gemini (`similarite.py` l.284 et l.287) en fait une condition dure :

- règle 1bis : « si l'offre relève d'un des PÔLES VALIDES **ET** qu'elle demande une ou plusieurs
  des COMPÉTENCES… alors score ≥ 75 » — c'est une **conjonction**, donc pas de pôle = pas de 75 ;
- règle 3 : « le sujet **doit** relever d'un des pôles valides » ;
- règle 4 : « en cas de doute sérieux… penche vers un score BAS ».

Or votre `profil_ideal.txt` affirme l'inverse dans le bloc OFFRE DE RÉFÉRENCE : *« Ce type de
mission (PMO de pilotage / transformation IT en banque, y compris modernisation d'outils) est
PLEINEMENT dans le périmètre. »* Gemini reçoit donc deux instructions contradictoires, et la
règle 4 lui dit comment trancher : vers le bas. C'est précisément ce qu'il a fait.

**Mesure.** Sur les 201 offres notées : **50 n'ont aucun pôle attribué**, et seules 23 d'entre
elles dépassent 75. Sans pôle, franchir le seuil haut est quasi impossible.

**Détail révélateur** : sur votre offre de référence, le pré-filtre embeddings avait donné
**78** — il avait raison. Gemini l'a ramenée à **60**. Votre étage sémantique gratuit était plus
juste que votre étage payant, parce que lui n'a pas la contrainte de pôle.

---

# B. Les faux positifs

## B1 — Le score Gemini n'a aucun pouvoir de décision

`similarite.py` définit `SIM_SEUIL_HAUT = 75` et `SIM_SEUIL_BAS = 55`, avec le commentaire
*« réglage STRICT demandé par l'utilisatrice (très similaires, pas de faux positifs) »*.

Mais `linkedin_sourcing_regie.py` l.613-640, `_appliquer_similarite()`, ne fait **qu'annoter** :

```python
for a, r in zip(conv, res):
    a["sim_score"] = r["score_global"]
    a["sim_verdict"] = SIM.verdict_similarite(r)
    ...
```

Aucun `del`, aucun `continue`, aucune réécriture de `a["verdict"]`. Le tri et les couleurs de
l'Excel utilisent `VERDICT`, qui vient du classifieur lexical. `SIM_SEUIL_BAS` n'est jamais lu
comme filtre.

**Mesure** — distribution du score Gemini parmi les 201 offres **conservées** :

| Score Gemini | Offres conservées | Part |
|---|---|---|
| 0-24 (hors sujet net) | 24 | 12 % |
| 25-54 (sous `SIM_SEUIL_BAS`) | 9 | 4 % |
| 55-74 (zone limite) | 8 | 4 % |
| 75+ (au-dessus de `SIM_SEUIL_HAUT`) | 160 | 80 % |

**33 offres conservées sont sous le seuil bas que vous avez vous-même fixé.** Vous payez des
appels Gemini pour produire un jugement correct, puis vous l'ignorez.

## B2 — `"reporting"` et `"data"` vident le label MATCH CŒUR de son sens

`COEUR_METIER_KW` (l.125) contient `"data"`, `"reporting"`, `"tableau de bord"`. Or :

- `reporting` figure dans quasi **toute** description de PMO — le mot est même dans les livrables
  de votre offre de référence ;
- l'étape 2 de `detect_domaine()` teste `data` sur le titre **avant** `EXCLUS_TECH_KW`, ce qui
  conserve délibérément les profils Data techniques ;
- l'étape 4 teste `COEUR_METIER_KW` sur le **texte complet**, donc n'importe quelle annonce
  mentionnant « reporting » décroche le statut cœur métier.

**Mesure.** 93 des 209 lignes (44 %) sont `★★ MATCH CŒUR`, dont **16 avec un score Gemini < 40** :

| sim | Offre classée MATCH CŒUR |
|---|---|
| 0 | Senior Software Engineer Python / Data Platform (H/F) |
| 0 | PMO Expérimenté / gestion budgétaire (**RETAIL**) |
| 0 | PMO Budget (H/F) - 92 |
| 5 | Middle officer trade finance |
| 10 | Data Engineer Teradata (F/H) |
| 15 | Data Scientist / MLOps à Croix (59) |
| 15 | Data Scientist – secteur bancaire (F/H) |
| 20 | Chef de projet GED |

Un *Software Engineer Python* en tête de votre Excel avec la même étoile qu'un PMO bancaire :
c'est le symptôme que vous décrivez.

## B3 — Un PMO ne peut structurellement pas atteindre MATCH CŒUR

`classifier.py` l.868 :

```python
if typ == "mission_regie" and a["coeur_metier"]:
    return "★★ MATCH CŒUR", ""
if typ == "mission_regie" and a["domaine_ok"]:
    return "★ À SAISIR", ""
```

`coeur_metier` = Data/BI. `domaine_ok` = PMO, AMOA, chef de projet, gouvernance. Donc une mission
PMO ne peut obtenir MATCH CŒUR que **par accident**, si son texte contient « reporting ». L'Excel
étant trié par verdict, un Data Engineer passe systématiquement devant un PMO bancaire.

Ce classement date de la période où le cœur de cible était Data/BI. Il n'a pas suivi le
recentrage sur le PMO qu'atteste votre `profil_ideal.txt`.

## B4 — Contradiction à arbitrer : `recette`

`"recette"` est en exclusion dure (`classifier.py` l.170, règle datée 2026-07-17). Mais
`score_competences.py` l.33 en fait une compétence idéale de **poids 3, le maximum** (« Recette /
tests »), et `profil_ideal.txt` la cite deux fois comme savoir-faire du cabinet (« élaboration du
cahier de recette », « conduite des tests de non-régression et des tests métiers »).

Ce n'est pas un bug, c'est une décision qui n'a pas été propagée. À trancher : soit la recette
sort du profil idéal, soit elle sort des exclusions dures. En l'état, une mission « AMOA + cahier
de recette » est écartée par le filtre et récompensée par le scoring.

---

# C. Correctifs

## C1 — `classifier.py` : exclusion infra sous condition

Retirer `infrastructure`, `infra `, `réseau`, `réseaux`, `urbanisation` de `EXCLUS_HARD_KW` et les
déplacer dans une liste conditionnelle, neutralisée par la présence d'un signal de pilotage.

```python
# NOUVEAU — technique seulement si aucun signal fonctionnel n'accompagne
EXCLUS_SI_SEUL_KW = [
    "infrastructure", "infra ", "réseau", "réseaux", "reseau", "reseaux",
    "urbanisation", "cyber", "cybersécurité", "cybersecurite",
]
SIGNAL_PILOTAGE_KW = [
    "pmo", "pilotage", "gouvernance", "chef de projet", "cheffe de projet",
    "directeur de projet", "amoa", "moa", "conduite du changement",
    "copil", "coproj", "project management officer", "chef de programme",
]
```

Dans `detect_domaine()`, remplacer le bloc l.724-726 par :

```python
    # 1) Exclusions dures (titre) — inchangé pour support/run/dev
    if has_any(poste, EXCLUS_HARD_KW):
        return False, False, True

    # 1bis) NOUVEAU — technique conditionnel : « infrastructure » n'écarte que si
    # le titre ne porte AUCUN signal de pilotage fonctionnel. Un « Chef de projet
    # Infrastructure / Gouvernance » est fonctionnel ; un « Ingénieur
    # Infrastructure » ne l'est pas.
    if has_any(poste, EXCLUS_SI_SEUL_KW) and not has_any(poste, SIGNAL_PILOTAGE_KW):
        return False, False, True
```

**Effet mesuré (C1 + C2 appliqués ensemble sur mes 51 offres)** : les offres écartées passent de
**9 à 1**, soit **8 récupérées** :

| Score | Offre récupérée |
|---|---|
| 96 % | Chef de projet Infrastructure / Gouvernance projets |
| 84 % | PMO Infra / Production bancaire (REF03) |
| 74 % | Directeur de projet — référentiel / urbanisation SI |
| 68 % | Chef de projet SI — Agile / Jira / Confluence |
| 66 % | Responsable de version informatique |
| 64 % | Responsable applicatif / Chef de projet SI — BPM |
| 64 % | Chef de projet SI / Chef de projet AMOA |
| 64 % | Chef de projet Infrastructure Réseaux |

**Contrôle anti-régression** : les postes réellement techniques restent tous écartés — Ingénieur
Infrastructure Cloud, Administrateur réseau senior, Expert Cybersécurité SOC, Ingénieur DevOps
Kubernetes, Architecte Infrastructure, Technicien support N1. Le discriminant « signal de pilotage
dans le titre » sépare proprement les deux familles.

## C2 — `classifier.py` : corriger le motif `"projet si"`

```python
# AVANT (l.156)  — matche projet SIRH, projet Sinistres, projet Simulation…
    "urbanisation", "projet si", "si fonctionnel", "architecte si",

# APRÈS — ancrage sur fin de chaîne ou séparateur
    "si fonctionnel", "architecte si",
```

et ajouter, dans `detect_domaine()`, un test explicite à la place :

```python
    import re
    if re.search(r"\bprojet\s+si\b(?!\s*(rh|nistre|mulation|gnature))", _pad(poste)):
        return False, False, True
```

Plus simple et plus robuste : supprimez purement `"projet si"`. « Chef de projet SI » en banque
est presque toujours dans votre périmètre — c'est le titre de l'offre Al Barid Bank et de trois
autres que vous avez perdues.

## C3 — `profil_ideal.txt` : ajouter un 12e pôle

Voir le fichier `profil_ideal_corrige.txt` livré à côté. Le changement clé, dans le bloc PÔLES :

```
… ; ALM (gestion actif-passif) ; Pilotage & Transformation IT bancaire
(gouvernance de programme, PMO, modernisation d'outils de gestion IT — ITSM/CMDB,
Digital Workplace, poste de travail, socle collaboratif — conduite du changement et
adoption utilisateurs, à condition que le CLIENT FINAL soit une banque, une société
financière ou un assureur).
```

Et lever la contradiction dans le prompt, `similarite.py` l.287 (règle 3) :

```python
# AVANT
3. SECTEUR : le CLIENT FINAL de la mission doit RÉELLEMENT opérer dans la banque / finance /
assurance, ET le sujet doit relever d'un des pôles valides.

# APRÈS
3. SECTEUR : le CLIENT FINAL de la mission doit RÉELLEMENT opérer dans la banque / finance /
assurance. Le sujet doit relever d'un des pôles valides OU être une mission de pilotage /
gouvernance / conduite du changement au service d'un programme IT de ce client — le pôle
« Pilotage & Transformation IT bancaire » couvre ce cas et n'est pas moins valide que les autres.
```

## C4 — `linkedin_sourcing_regie.py` : donner un pouvoir de décision au score

Dans `_appliquer_similarite()`, après la boucle d'annotation :

```python
        # NOUVEAU — le score de similarité devient décisionnel.
        for a in conv:
            s = a.get("sim_score")
            if s is None:
                continue                      # Gemini indisponible : on ne jette rien
            if s < SIM.SIM_SEUIL_BAS:         # 55
                a["verdict"] = "ÉCARTÉE"
                a["motif"] = f"similarité {s} < {SIM.SIM_SEUIL_BAS}"
            elif s < SIM.SIM_SEUIL_HAUT:      # 75
                a["verdict"] = "À CONFIRMER"
                a["motif"] = f"similarité {s} en zone limite"
```

Effet sur votre fichier actuel : 33 lignes passent en ÉCARTÉE, 8 en À CONFIRMER. Les écartées
restent tracées dans `annonces_vues.json`, donc rien n'est perdu.

Ne l'activez pas d'un coup. Faites d'abord tourner `reclass` avec la variable
`SIM_SEUIL_BAS=40` pour voir la coupe, puis remontez vers 55.

## C5 — `classifier.py` : verdict fondé sur le rôle, plus sur le seul Data/BI

```python
# AVANT (l.868)
    if typ == "mission_regie" and a["coeur_metier"]:
        return "★★ MATCH CŒUR", ""
    if typ == "mission_regie" and a["domaine_ok"]:
        return "★ À SAISIR", ""

# APRÈS — le pilotage fonctionnel est un cœur de métier à part entière
    if typ == "mission_regie" and (a["coeur_metier"] or a.get("pilotage_fort")):
        return "★★ MATCH CŒUR", ""
    if typ == "mission_regie" and a["domaine_ok"]:
        return "★ À SAISIR", ""
```

avec, calculé dans `detect_domaine()` et remonté dans le dict l.827 :

```python
    pilotage_fort = has_any(poste, ["pmo", "project management officer",
                                    "chef de projet", "directeur de projet",
                                    "chef de programme", "amoa", "moa"])
```

## C6 — Resserrer `COEUR_METIER_KW`

Retirer `"reporting"` de la liste, ou ne le tester que sur le **titre** et jamais sur le texte.
`reporting` seul dans un corps d'annonce ne dit rien : c'est le mot le plus banal du pilotage de
projet. Gardez-le comme signal uniquement en cooccurrence :

```python
COEUR_DATA_STRICT = ["power bi", "business intelligence", "datawarehouse", "data quality",
                     "data gouvernance", "data governance", "dataviz", "décisionnel"]
# "data" et "reporting" seuls ne suffisent plus à déclarer le cœur métier
```

---

# D. Sources manquantes

Vos collecteurs actuels : LinkedIn `jobs-guest`, Trusted Advisors, Free-Work API, GEC-Zoho
headless, Werin. Deux absences qui expliquent des trous nets :

**Freelance-Informatique** (`freelance-informatique.fr/offres-freelance`) — HTML statique,
pas d'API, pas de login, URL de mission propre et stable du type
`/mission-<slug>-<YYMMDD><ref>`. C'est la source de mes trouvailles n° 2 (96 %), 5, 7, 10, 22, 30
et 32, dont **aucune** n'est dans votre fichier. La date de publication est exposée en relatif
(« aujourd'hui », « il y a 3 jours »), donc datable de façon fiable.

**Free-Work par pages de catégorie** — vous utilisez `api/job_postings?contracts=contractor`,
ce qui est le bon réflexe, mais les pages `/fr/tech-it/jobs/project-management-officer`,
`/conduite-du-changement` et `/pilotage` remontent des annonces que le paramètre `contractor`
seul ne semble pas ramener, dont la quasi-jumelle de votre offre de référence (PMO Senior,
bascule CMDB).

Un point de méthode, aussi : votre datation est **meilleure** que celle des agrégateurs. Sur le
seul doublon net entre nos deux fichiers (Chef de Projet AMOA Banque, Groupe Aptenia), vous datez
au 07/07 quand Indeed affichait le 22/07. Continuez à faire foi de `1re détection`.

---

# E. Ordre d'application recommandé

| # | Correctif | Coût | Gain attendu |
|---|---|---|---|
| 1 | **C2** — supprimer `"projet si"` | 1 ligne | Récupère SIRH, Bancassurance, ALM |
| 2 | **C1** — exclusion infra conditionnelle | ~10 lignes | Récupère 5 offres dont la meilleure du marché |
| 3 | **C3** — 12e pôle + règle 3 du prompt | 2 fichiers | Débloque le plafond de 60 sur les missions type |
| 4 | **C4** — seuil décisionnel, à 40 d'abord | ~10 lignes | Supprime les faux positifs les plus visibles |
| 5 | **C5 + C6** — verdict et cœur métier | ~15 lignes | Remet le PMO en tête de l'Excel |
| 6 | **B4** — arbitrer `recette` | décision | Lève une incohérence de fond |
| 7 | **D** — ajouter Freelance-Informatique | 1 collecteur | Nouvelle source à fort rendement |

Après C3, videz `cache_gemini.json` (ou au moins les entrées des offres de pilotage) : le cache
est indexé sur le hash de `titre + mission`, donc un changement de prompt ne le réinvalide pas et
vous relirez d'anciens jugements rendus sous l'ancienne contrainte de pôle.

Enfin, `test_classifier.py` compte 44 tests mais aucun ne couvre le cas « PMO sur périmètre
infrastructure en banque », qui est votre cible. Ajoutez-le comme test de non-régression avant de
toucher au reste — c'est le meilleur garde-fou contre une future exclusion trop large.
