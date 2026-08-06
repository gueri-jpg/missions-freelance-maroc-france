# Sourcing missions freelance / régie — secteur bancaire (Maroc)

Outil de veille automatisée des **missions en régie / freelance** dans la **banque**
au Maroc, pour les profils **PMO, AMOA/MOA/MOE, Chef de projet, Data / BI / Power BI,
Data Gouvernance, Business Analyst, Product Owner, Développeur**.

Il collecte plusieurs sources, applique automatiquement les critères de tri, et produit
un **Excel des offres convenables**, fusionné avec le fichier de référence, sans doublon.

---

## 1. Installation

```bash
pip install requests beautifulsoup4 openpyxl lxml
```
Python 3.13 (Windows). Rien d'autre à configurer.

## 2. Utilisation

```bash
python linkedin_sourcing_regie.py maroc      # collecte + classification + fusion + Excel
python linkedin_sourcing_regie.py reclass maroc   # re-classe le cache, SANS réseau (rapide)
python linkedin_sourcing_regie.py france     # (à activer plus tard)
```

Réglages via variables d'environnement (facultatif) :
| Variable | Défaut | Rôle |
|---|---|---|
| `LKD_PAGES` | 2 | pages LinkedIn par requête (10 offres/page) |
| `LKD_MAX_DETAIL` | 300 | plafond de fiches LinkedIn lues en détail |
| `LKD_QUERY_LIMIT` | 0 | limite le nb de requêtes (0 = toutes) |

Sur Windows, préfixer par `PYTHONUTF8=1` (ou via `run_daily.ps1`) pour éviter les
plantages d'encodage des emojis.

## 3. Sources

| Source | Accès | Remarque |
|---|---|---|
| **LinkedIn** | endpoint public `jobs-guest` (sans connexion) | n'utilise PAS votre compte |
| **Trusted Advisors** | flux JSON `jobs.trustedadvisors-group.com/jobs.json` | Maroc — ~96 % d'archive → filtré par âge |
| **Free-Work** (France) | API REST `free-work.com/api/job_postings?contracts=contractor` | **grosse source FR**, expose le TJM + durée |
| **GEC-Zoho** (Maroc) | **navigateur headless** (Playwright/Chromium) sur `gec-groupe.zohorecruit.com` | cabinet régie banque — SPA JS, ~30 missions |
| **Werin Group** | JSON-LD sur `/jobs/` | Maroc — peu de banque (data/télécom) |
| **Fichier de référence** | `Sourcing postes freelance M&F.xlsx` (onglets Maroc + France) | importé tel quel dans 2 onglets à part |

Headless requis pour GEC-Zoho : `pip install playwright && python -m playwright install chromium`
(dégrade proprement si absent). Sources encore écartées : Capfi (hors cible),
Comet / Cherry-pick / Collective (login requis), missions-freelance.ma (structure opaque).

Les offres **VIVIER** (ouvertes mais anciennes, 22–90 j) sont **retirées** par défaut
(`LKD_KEEP_VIVIER=1` pour les réafficher).

Pour ajouter une source : écrire un collecteur dans `sources.py` qui renvoie des
« annonces » (mêmes clés) et l'ajouter au registre `COLLECTORS`.

## 4. Comment une mission devient « convenable » (les 4 filtres)

La logique vit dans `classifier.py` (couche pure, testée). Une mission est **convenable**
si elle passe les 4 conditions ; sinon **ÉCARTÉE** (avec motif).

1. **RÉGIE (pas CDI)** — *le texte prime sur le label LinkedIn, qui n'exclut jamais.*
   - Signaux forts : `mission freelance`, `TJM`, `en régie`, `assistance technique`,
     `pour/auprès de notre client`, `REF+chiffres`, `X mois renouvelables`, `portage`…
   - Client final (banque qui recrute pour elle-même) → CDI interne = **écarté**,
     *sauf* signal freelance/B2B fort explicite (une banque peut chercher un freelance).
   - Régie livrée en **salariat seul** (« CDI de mission », sans B2B) → **à confirmer**.
2. **BANQUE** — `banque, bancaire, monétique, SWIFT, ALM, core/digital banking, crédit,
   cash management, trade finance…` → OUI ; cabinet spécialisé banque (BROME, GEC,
   Adaptive, FININFO) → PROBABLE ; sinon NON = écarté.
3. **DOMAINE** — cœur métier (data, BI, Power BI, data gouvernance/quality…) ou domaine OK
   (AMOA, PMO, chef de projet, business analyst, PO, dev, chargé de recette). Principe
   directeur (depuis le 2026-08-03) : **c'est le RÔLE demandé qui décide, pas le domaine
   technique du projet**. Un PMO / AMOA / chef de projet qui pilote un projet
   d'infrastructure, réseau ou cybersécurité chez une banque reste **dans** le périmètre ;
   un ingénieur, architecte technique, administrateur ou développeur reste **hors**
   périmètre, même sur un sujet fonctionnel. Concrètement : `infrastructure`, `réseau(x)`,
   `cyber`/`cybersécurité`, `urbanisation`, `recette`, `homologation` n'excluent que s'ils
   sont **seuls**, sans aucun signal de pilotage dans le titre (`chef de projet`, `pmo`,
   `amoa`, `gouvernance`…) — ce ne sont plus des exclusions dures. Exception maintenue :
   « chef de projet SI » **nu** (sans autre signal) reste hors périmètre — l'acronyme « SI »
   seul est trop générique/ambigu pour attester du fonctionnel.
4. **FRAÎCHEUR** — LinkedIn n'expose pas la clôture → estimée par **âge + nb de candidats**.
   0-7 j NOUVEAU · 8-21 j OUVERTE · peu de candidats (≤30, ≤180 j) ou republié → ROUVERTE ·
   flux ATS encore listé (≤90 j) ou besoin récurrent → VIVIER · au-delà → écarté (âge).

Les 11 pôles métier bancaires (Crédit & Engagement, Salle des marchés, Gestion d'actifs,
Intermédiation boursière, Paiements & Monétique, SIRH, Risques, Planification budgétaire,
Bancassurance, KYC & Conformité, ALM) sont complétés d'un **12e pôle** :
**Pilotage & Transformation IT bancaire** — gouvernance de programme, PMO, modernisation
d'outils IT (CMDB, ITSM, Digital Workplace, poste de travail…) et conduite du changement,
à condition que le client final soit une banque, une société financière ou un assureur.
Voir `profil_ideal_corrige.txt`.

### Verdict final (tri de l'Excel)
```
ÉCARTÉE si : hors domaine · hors banque · CDI · clôturée · trop ancienne · hors profil idéal
★★ MATCH CŒUR = régie + banque + (cœur métier data/BI OU pilotage fort : PMO/AMOA/
                chef de projet/chef de programme) + fenêtre ouverte
★ À SAISIR    = régie + domaine OK (AMOA/PMO/CDP…) + ouverte
À CONFIRMER   = ambigu → message B2B fourni (accessibilité société de conseil ?)
VIVIER        = ouvert mais ancien / besoin récurrent → candidature spontanée
★ RÉFÉRENCE   = missions de votre fichier (fusionnées, contacts conservés)
```
Un PMO/AMOA n'est donc plus relégué derrière un Data Engineer par défaut : le pilotage
fonctionnel est désormais un cœur de métier à part entière (`pilotage_fort`), pas seulement
la Data/BI.

Bonus **multi-ESN** : 2 cabinets postant la même mission à < 15 j = une banque consulte
plusieurs cabinets → postuler aux deux.

### Filtre de similarité (au-dessus des 4 filtres, `similarite.py`)

Un 5e filtre, **décisionnel**, tourne sur les offres **NEUVES** uniquement (jamais sur
l'existant du fichier) : pré-filtre embeddings gratuit (bouncer permissif), puis Gemini
juge chaque offre contre le profil idéal et pose un `score_global` 0-100. Sous
`SIM_SEUIL_BAS` (55 par défaut) → écartée du fichier (« hors profil idéal ») ; entre
`SIM_SEUIL_BAS` et `SIM_SEUIL_HAUT` (75) → À CONFIRMER ; au-dessus → conservée. Pilotable
par `SIM_FILTRE_ACTIF=0` (coupe-circuit, ex. pour retester un changement de seuil sans
perdre d'offres), `SIM_SEUIL_BAS`/`SIM_SEUIL_HAUT` par variables d'environnement. Le cache
des jugements (`cache_gemini.json`) est invalidé automatiquement quand `PROMPT_VERSION`
change (modification du prompt ou du profil idéal) ; `--vider-cache-gemini` force une purge
immédiate. Exemple : `SIM_FILTRE_ACTIF=1 SIM_SEUIL_BAS=40 python linkedin_sourcing_regie.py reclass maroc`
pour observer la coupe avant de remonter le seuil vers 55.

## 5. Sortie

`Sourcing_regie_banque_FUSION_<date>.xlsx` — onglet Maroc, **offres convenables uniquement**,
triées par verdict. 22 colonnes : les colonnes historiques (poste, mission, entité, ville,
exigence, lieu, contact, durée, SOURCE cliquable, publication) + VERDICT, type réel, banque,
cœur métier, candidats, âge, fenêtre, multi-ESN, question B2B, 1re détection, dern. vérif.,
provenance. Couleurs par verdict. Les écartées ne sont pas perdues : tracées dans
`annonces_vues.json`.

## 6. Automatisation

`run_daily.ps1` + tâche Windows « SourcingLinkedIn_Regie_Banque » → exécution chaque jour à
**07:30** (collecte toutes sources → fusion → Excel). Journaux dans `logs/`.

## 7. Fichiers

| Fichier | Rôle |
|---|---|
| `linkedin_sourcing_regie.py` | orchestrateur (collecte, fusion, Excel) |
| `classifier.py` | logique de décision (tous les filtres) — pur, testable |
| `sources.py` | sources hors LinkedIn (Trusted Advisors, Werin) |
| `test_classifier.py` | tests unitaires (`python -m unittest test_classifier`) |
| `run_daily.ps1` | lanceur quotidien |
| `cache_annonces_maroc.json` | cache brut (permet `reclass` hors ligne) |
| `annonces_vues.json` | historique (1re détection / verdict / dern. vérif.) |

## 8. Limites connues

- **Clôture / republié / « recrute activement »** : non exposés en accès public LinkedIn
  (réservés au mode connecté) → fraîcheur estimée par âge + candidats.
- **Banques en direct** : n'affichent pas de missions freelance sur LinkedIn (la régie
  passe par les cabinets).
- **GEC Zoho / Capfi** : job boards en JavaScript → non scrapables sans navigateur headless
  (GEC apparaît de toute façon sur LinkedIn + fichier de référence).
- **« Chef de projet SI » nu** reste hors périmètre par choix assumé (l'acronyme « SI » est
  trop générique/ambigu seul) — il faut un signal de pilotage supplémentaire dans le titre
  (pmo, amoa, gouvernance, agile…) pour lever l'exclusion. `infrastructure`/`réseau`/`cyber`
  sont, eux, sauvés par « chef de projet » seul (structure "chef de projet X" = pilote X).
- **Filtre de similarité dépendant de Gemini** : si la clé/API est indisponible ou en quota,
  les offres neuves sont marquées « À VÉRIFIER » plutôt que jugées — jamais écartées à tort,
  mais le tri fin (score/pôle) n'a lieu qu'au retour de Gemini.
- **Cache des embeddings du profil** (`.cache_embeddings_ideal.pt`) : un incident le
  2026-08-02 a montré qu'un cache corrompu (vecteurs factices, ex. issus d'un faux encodeur
  de test) peut fausser silencieusement TOUT le pré-filtre sans erreur visible, tant que sa
  signature (hash du profil + nom du modèle) reste valide. Un garde-fou rejette désormais un
  cache dont les vecteurs font moins de 16 dimensions, mais un futur mode de corruption
  différent resterait possible — en cas de doute, supprimer le fichier pour forcer un
  recalcul avec le vrai modèle.
