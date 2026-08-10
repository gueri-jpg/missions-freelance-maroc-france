# Veille des appels d'offres publics IT — CFConsulting

Pipeline Python de détection des appels d'offres publics français en
**procédure adaptée**, domaine **IT strict**, montant **< 100 000 € HT**,
avec récupération best-effort des documents de consultation (DCE), synthèse
IA, et centralisation dans un fichier Excel exploitable pour la prospection.

## ⚠️ Règle d'exactitude

Aucune donnée n'est inventée. Si une information est absente d'une source,
la cellule reste **vide ou "non précisé"** — jamais d'estimation. Chaque
ligne exportée porte le lien vers sa source. Ce pipeline **ne prétend pas à
l'exhaustivité** (cf. [Limites de couverture](#limites-de-couverture)
ci-dessous). Les données BOAMP sont réutilisées sous
[Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/)
(DILA) — la source est mentionnée sur chaque ligne (`Lien avis`).

## ⚠️ Sécurité — dossier de projet et clés API

**Ne placez jamais ce projet (ni son fichier `.env`) dans un dossier
synchronisé par un client cloud (OneDrive, Google Drive, Dropbox...).** Toute
clé API stockée dans `.env` serait alors synchronisée vers le cloud du
fournisseur, en dehors de tout contrôle Git, même sans `push`. Si vous
développez depuis un dossier OneDrive (comme c'est le cas de l'exemplaire
livré ici), déplacez le projet vers un chemin local hors synchronisation
avant d'y renseigner de vraies clés API, ou excluez explicitement le dossier
de la synchronisation OneDrive.

`.env` est exclu de Git par `.gitignore`. Ne le commitez jamais.

## Installation

Prérequis : Python 3.11+ (testé en 3.13), accès réseau sortant.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
playwright install chromium     # navigateur headless pour le téléchargement des DCE

copy .env.example .env          # puis renseigner GEMINI_API_KEY (gratuit)
```

## Usage

Le pipeline s'exécute en 3 étapes indépendantes, chacune met à jour le même
fichier Excel de façon incrémentale (dédoublonnage par identifiant) :

```bash
# 1. Collecte + classification -> data/veille_appels_offres.xlsx
python run_collect.py --adaptee --max-records 200

# Découverte des champs réels de l'API BOAMP (diagnostic / debug)
python run_collect.py --discover

# 2. Téléchargement best-effort des DCE pour les avis pertinents
python run_download.py --limit 50

# 3. Synthèse IA des DCE téléchargés (Gemini par défaut, gratuit)
python run_synthesis.py --provider gemini --limit 20
```

### Options utiles

| Option | Module | Effet |
|---|---|---|
| `--adaptee` | run_collect.py | Ne garder que les procédures adaptées (MAPA). Une procédure vide/"NC" n'est **jamais** exclue par ce filtre — elle est marquée "procédure à vérifier". |
| `--skip-approch` | run_collect.py | Ne pas interroger l'API APProch (avis provisionnels) |
| `--skip-place` | run_collect.py | Ne pas scraper PLACE/Maximilien (profils acheteurs complémentaires) |
| `--provider anthropic` | run_synthesis.py | Utilise Claude au lieu de Gemini (clé `ANTHROPIC_API_KEY` requise) |

## Architecture

```
config.py            CPV cibles, mots-clés IT, exclusions BTP, seuils, chemins
collector_boamp.py    Interroge l'API BOAMP (source principale)
collector_approch.py  Interroge l'API APProch (projets prévisionnels)
collector_place.py    Scrape PLACE + Maximilien (profils acheteurs, sans API)
filter_classify.py    Pertinence IT, procédure, exclusion accords-cadres
downloader.py          Téléchargement DCE best-effort via Playwright
extractor.py           PDF (pdfplumber) + DOCX (python-docx) -> texte ; ZIP
synthesis_agent.py     Synthèse LLM (Gemini / Anthropic)
excel_writer.py         Écriture/màj incrémentale, dédoublonnage
run_collect.py / run_download.py / run_synthesis.py   Points d'entrée CLI
tests/                  Suite pytest
```

## Sources officielles

1. **API BOAMP** (source principale, DILA, Licence Ouverte 2.0, gratuite)
   https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records
   Doc : https://www.data.gouv.fr/datasets/boamp
2. **API APProch** — projets d'achats prévisionnels (DAE, open data), saisis
   volontairement par l'acheteur -> toujours marqués "estimation
   prévisionnelle — à confirmer" dans un onglet séparé.
   https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/projets-dachats-publics/records
3. **PLACE** (marches-publics.gouv.fr) et **Maximilien** (marches.maximilien.fr,
   portail des marchés publics d'Île-de-France) — profils acheteurs sans API
   publique, interrogés via un scraping best-effort de leur formulaire de
   recherche public (sans compte), filtré sur "Procédure adaptée". Couvre les
   MAPA publiées uniquement sur profil acheteur, sans passage par le BOAMP.
   Bonus : le lien "Télécharger le RC", quand disponible, pointe vers un PDF
   accessible sans authentification.
4. **CPV** : https://simap.ted.europa.eu (famille 72 = services informatiques)

### Sources évaluées et écartées

- **TED** (Tenders Electronic Daily, JOUE) : l'API officielle a été testée en
  direct — les seuils de publication européens (~140 000 € HT pour les
  services) excluent structurellement les MAPA < 100 000 € HT ciblées ici.
- **data.gouv.fr** (recherche élargie au-delà d'APProch) : aucun autre jeu de
  données pertinent identifié pour la veille IT.
- **Agrégateurs privés** (marchesonline.com, francemarches.com,
  centraledesmarches.com, vecteurplus.com, klekoon.com) : aucune API
  publique, comptes payants et/ou protections anti-bot actives (403,
  Cloudflare Turnstile) — non intégrables sans abonnement.
- **JAL / presse locale** : aucune API libre connue à ce jour — reste un
  angle mort documenté (un acheteur en MAPA peut légalement publier
  uniquement en JAL, sans BOAMP ni profil acheteur).

## Limites de couverture

- **Le BOAMP ne contient pas tous les MAPA < 90 000 € HT** : sous ce seuil,
  l'acheteur choisit librement son support de publicité (presse/journal
  d'annonces légales, profil acheteur seul...). PLACE/Maximilien comblent une
  partie de cet angle mort (profils acheteurs), pas la presse/JAL.
- **Presse / journaux d'annonces légales (JAL)** n'exposent pas d'API libre
  connue à ce jour — non couverts par ce pipeline (à vérifier au cas par cas
  si une source structurée apparaît).
- **PLACE/Maximilien sont scrapés (pas d'API)** : formulaire HTML légacy
  (PRADO), best-effort — le rechargement après une action (recherche,
  changement de page) peut prendre plusieurs secondes sur les grands jeux de
  résultats (recherche "floue" par défaut, parfois des centaines de
  résultats pour un mot-clé pourtant précis) ; `collector_place` attend
  explicitement ce délai avant de lire la page. Aucun montant ni CPV n'est
  exposé sur la page de résultats (seule la classification par mots-clés
  s'applique, pas le signal CPV).
- **APProch est déclaratif et non exhaustif** : les acheteurs ne sont pas
  tenus d'y publier tous leurs projets, et les montants y sont des
  estimations prévisionnelles de l'acheteur, pas des montants contractuels.
- **La classification IA du domaine** ("IT confirmé"/"à vérifier"/"hors IT")
  est un filtre heuristique best-effort (CPV + mots-clés), pas une analyse
  humaine. Les lignes "à vérifier" nécessitent une revue manuelle avant
  d'être écartées ou retenues. Voir `filter_classify.classify_domain` pour
  la logique exacte, notamment la gestion des termes ambigus "AMOA"/
  "maîtrise d'ouvrage" (génériques à tous les secteurs, pas seulement l'IT).
- **Le téléchargement des DCE (Playwright)** est best-effort : de nombreuses
  plateformes de dématérialisation exigent une authentification (jamais
  contournée par ce pipeline — statut "connexion requise" alors renvoyé) ou
  ont une structure de page non standard. Le repli systématique est
  "téléchargement manuel — voir lien".
- **Aucune exhaustivité n'est garantie ni implicite.** Ce pipeline est un
  outil d'aide à la détection, pas un système de veille certifié complet.

## Respect des CGU et de robots.txt

`downloader.py` vérifie `robots.txt` avant toute navigation automatisée,
applique un délai minimal entre requêtes vers un même hôte
(`config.REQUEST_DELAY_SECONDS`), envoie un User-Agent explicite identifiant
l'outil, et ne contourne jamais une page d'authentification. En cas de doute
sur les CGU d'une plateforme spécifique, privilégier le téléchargement
manuel (statut par défaut du pipeline).

## Fournisseur LLM — Gemini (gratuit, par défaut) vs Anthropic (option)

**Gemini (Google AI Studio, free tier)** :
- Modèles Flash / Flash-Lite uniquement (pas de Pro) sur le free tier.
- **Quota constaté empiriquement (clé standard, juillet 2026) : `gemini-2.5-flash`
  est plafonné à 20 requêtes PAR JOUR** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`),
  pas un simple débit par minute. Un 429 dans ce cas ne se résout pas en
  patientant quelques secondes — il faut attendre le lendemain (reset ~minuit
  Pacifique) ou basculer sur `gemini-2.5-flash-lite`, qui a son propre quota
  séparé (`python run_synthesis.py --model gemini-2.5-flash-lite`). Les
  quotas exacts varient selon le compte/projet — vérifier sur
  https://ai.dev/rate-limit avant de planifier un traitement par lot.
  `synthesis_agent.py` gère les 429 et les 500/503 (surcharge serveur) avec
  retry et backoff exponentiel automatique, mais cela ne contourne pas un
  quota journalier épuisé.
- Les données envoyées au free tier peuvent être utilisées par Google pour
  améliorer ses produits (cf. conditions Google AI Studio) — à valider côté
  conformité avant tout usage professionnel intensif, même si les DCE
  traités sont des documents publics.
- Une clause spécifique EEE/UK/Suisse peut imposer le passage au tier
  payant pour un usage professionnel.
- Lit le PDF nativement (envoi direct du fichier, pas besoin d'extraction
  de texte préalable).
- Vérifier l'id de modèle exact avant mise en production :
  https://ai.google.dev/gemini-api/docs/models

**Anthropic (Claude, option payante)** : modèle par défaut `claude-haiku-4-5`
(rapide/économique), support PDF natif également, retry/backoff géré
automatiquement par le SDK officiel. Vérifier l'id de modèle exact avant
mise en production : https://docs.claude.com

Dans les deux cas : consigne stricte de renvoyer `"non précisé"` pour toute
information absente du document — jamais d'invention de valeur — et
`temperature=0`. Pour les pénalités, la clause du CCAP est extraite
**verbatim** ; le CCAG référencé (CCAG-TIC ou CCAG-PI) est noté tel quel
s'il apparaît, sans supposer de formule de calcul non explicite.

## Tests

```bash
pytest -q
```

70 tests couvrant notamment :
- Classification IT confirmé / à vérifier / hors IT sur CPV et mots-clés,
  y compris les cas ambigus AMOA/maîtrise d'ouvrage rencontrés en collecte
  réelle (écologie, accessibilité de bâtiments, signalétique — à tort
  classés IT dans une version antérieure du filtre, corrigé et verrouillé
  par des tests de non-régression).
- Filtrage procédure adaptée (`--adaptee`) sans exclusion des procédures
  vides/NC.
- Exclusion des accords-cadres au-delà du seuil PME, conservation des
  marchés simples sans montant connu.
- Extraction robuste par recherche de clé récursive (préfixes `cbc:`/`cac:`
  eForms vs ancien schéma XSD BOAMP), sur des fixtures reproduisant les
  structures réelles observées via l'API.
- Provider Gemini mocké : réponse JSON valide, gestion du retry sur 429.
- Synthèse : renvoi systématique de `"non précisé"` pour tout champ absent.
- Excel : dédoublonnage par identifiant, colonnes DCE vides tant que la
  synthèse n'a pas tourné.

## Colonnes de l'Excel

`Référence/ID | Source | Date publication | Date limite | Acheteur |
Département | Objet/Mission | Domaine | Procédure | Type de contrat | CPV |
Montant estimé | Délai/durée | Calendrier | Pénalités | Présentiel |
Références exigées | Grille de notation | Lien avis | Lien profil
acheteur/DCE | Statut téléchargement | Statut synthèse | Remarques | Date de
collecte`

Un second onglet **"Projets à venir (APProch)"** liste séparément les
projets d'achats prévisionnels, non exhaustifs par nature.
