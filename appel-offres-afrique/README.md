# Veille des appels d'offres publics IT — Côte d'Ivoire / Maroc — CFConsulting

Pipeline Python de détection des appels d'offres publics IT en Côte d'Ivoire
et au Maroc, ciblant les opportunités accessibles à une PME de conseil,
avec centralisation dans un fichier Excel exploitable pour la prospection.
Même philosophie que le pipeline France (`../APPEL_OFFRES/`) : aucune donnée
n'est inventée, chaque ligne porte le lien vers sa source, la couverture
n'est pas garantie exhaustive (cf. [Limites de couverture](#limites-de-couverture)).

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows

pip install -r requirements.txt
playwright install chromium     # navigateur headless pour la source Maroc
```

## Usage

```bash
python run_collect.py                               # collecte complète (~10-15 min, cf. ci-dessous)
python run_collect.py --skip-maroc --skip-maroc-pps   # DGMP-CI seul (rapide)
python run_collect.py --maroc-max-pages 60           # pousser la couverture PMMP (cf. limite ci-dessous)
python run_collect.py --skip-maroc-enrichment        # ne pas récupérer montant/caution (plus rapide)
python run_collect.py --maroc-seuil-montant-mad 500000   # seuil d'exclusion montant personnalisé
python run_collect.py --maroc-pps-max-documents 200  # PPS Maroc : élargir l'échantillon examiné
python run_collect.py --from-cache data/cache_non_ecrit_PMMP.json   # rejoue une écriture Excel échouée sans re-scraper
python run_collect.py --skip-ci --skip-maroc --skip-maroc-pps --include-onda   # ONDA seul (rapide, ~15s)
python run_collect.py --skip-ci --skip-maroc --skip-maroc-pps --skip-bad       # BCEAO seul (rapide, ~15s)
python run_collect.py --skip-ci --skip-maroc --skip-maroc-pps --skip-bceao     # BAD seul (rapide, ~15s)
python run_collect.py --bad-country-filter "Sénégal"  # flux BAD "projets" filtré sur un autre pays UEMOA/BAD
```

**ONDA est désactivé par défaut** (`--include-onda` pour l'activer) — cf.
[Sources évaluées et écartées](#sources-évaluées-et-écartées) pour le détail :
constaté en direct, 0 avis sur 14 survivent au filtre une fois le scope
correctement appliqué (formation/certification exclue, même sur un sujet
IT réel).

Le défaut `--maroc-max-pages 40` : **testé en direct à deux reprises, le
portail interrompt lui-même la pagination (lien "page suivante" disparu, ou
navigation en échec) systématiquement autour de la page 35-37 sur ~110
possibles** — vraisemblablement une limite de session côté serveur, pas un
bug du collecteur (aucune erreur explicite, comportement reproductible).
Pousser au-delà de 40 n'a rien changé au résultat final lors des tests
(exactement les mêmes avis retenus) — augmenter reste possible
(`--maroc-max-pages`) si le portail change de comportement, sans certitude
de gain. Compter ~6-8 minutes pour cette étape par défaut, plus ~1-2
minutes pour l'enrichissement montant/caution (une requête HTTP par avis
candidat retenu). Pour un run quotidien plus rapide, utiliser `--skip-*`
pour ne rafraîchir qu'une source à la fois.

**Si l'écriture Excel échoue** (fichier ouvert dans Excel, verrouillé par
une synchronisation cloud...), les données déjà collectées ne sont **jamais
perdues** : elles sont sauvegardées dans
`data/cache_non_ecrit_<source>.json`. Fermez le fichier puis rejouez
l'écriture avec `--from-cache` (quelques secondes) plutôt que de refaire
tout le scraping réseau.

## Architecture

```text
config.py             Mots-clés IT, seuils PME, URLs sources, chemins
collector_ci.py        Avis actifs DGMP-CI (marchespublics.ci/appel_offre)
collector_ci_ppm.py     PPM prévisionnel CI — RETIRÉ du pipeline, cf. Sources évaluées et écartées
collector_maroc.py      Avis PMMP (marchespublics.gov.ma), catégorie IT (Playwright)
collector_maroc_pps.py  Programme prévisionnel PMMP (ListePPs) — best-effort, PDF non structurés
collector_onda.py       Avis ONDA (onda.ma) — désactivé par défaut, cf. Sources évaluées et écartées
collector_bceao.py      Avis BCEAO (bceao.int) — régional UEMOA, requests seul
collector_bad.py        Avis BAD/AfDB (afdb.org) — 2 flux RSS, requests seul
filter_classify.py      Classification domaine IT (reprise de APPEL_OFFRES/), filtre date/type
excel_writer.py          Écriture/màj incrémentale, dédoublonnage, protection lignes surlignées/supprimées
run_collect.py           Point d'entrée CLI
tests/                   Suite pytest (offline, sans appel réseau)
```

## Sources officielles

### Côte d'Ivoire

1. **DGMP — avis actifs** (`https://marchespublics.ci/appel_offre`) : page
   HTML statique, rendue côté serveur, sans compte requis, sans `robots.txt`
   publié (404 constaté — aucune règle explicite trouvée). ~980 avis
   constatés, tenue à jour jusqu'à la date du jour. **Voir la limite majeure
   ci-dessous.**

Le PPM (Plans de Passation des Marchés, programme prévisionnel) a été
**retiré du pipeline** — cf.
[Sources évaluées et écartées](#sources-évaluées-et-écartées) pour le détail.

### Maroc

1. **PMMP — Portail Marocain des Marchés Publics**
   (`https://www.marchespublics.gov.ma`), catégorie officielle
   `domaineActivite=3.19` ("Services de technologies de l'information et
   télécommunications", équivalent du CPV 72 pour ce référentiel). Recherche
   multicritères accessible sans compte. **Constaté empiriquement : ce
   portail tourne sur le même moteur "profil acheteur" (PRADO postback,
   conventions d'identifiants `ctl0_CONTENU_PAGE_...`) que PLACE/Maximilien
   en France** — `collector_maroc.py` réutilise directement les techniques
   de `APPEL_OFFRES/collector_place.py` (Playwright, extraction JS,
   pagination). Données réellement fraîches et actives (dates limites
   observées jusqu'à plusieurs mois dans le futur), contrairement à la
   source DGMP-CI — voir limite ci-dessous. **Montant estimatif et caution
   provisoire** sont récupérés en enrichissement (page détail de chaque
   avis retenu, `EntrepriseDetailConsultation` — rendue côté serveur,
   `requests` seul suffit) : champ "Estimation (en Dhs TTC)" et "Caution
   provisoire". Les avis dont le montant dépasse un seuil
   (`--maroc-seuil-montant-mad`, 1 000 000 MAD par défaut) sont exclus —
   hors cible PME de conseil au-delà. Un **lien DCE** est également fourni
   par avis (formulaire de demande de téléchargement, choix "anonyme"
   disponible sans compte — remplissage non automatisé, cf. Limites).
2. **PMMP — Programme prévisionnel** (`index.php?page=entreprise.ListePPs`)
   : équivalent marocain du PPM ivoirien, mais structurellement très
   différent — ce n'est PAS un document centralisé et structuré, c'est un
   **dépôt de ~5 600+ fichiers PDF individuels** téléversés indépendamment
   par chaque acheteur public (une ligne du site = un fichier, pas un
   projet). `collector_maroc_pps.py` télécharge et tente d'extraire le texte
   des documents les plus récents (best-effort, borné par
   `--maroc-pps-max-documents`), ne conserve que ceux où un mot-clé IT
   apparaît, et écarte silencieusement les documents sans texte
   extractible — voir limite ci-dessous, le rendement de cette source est
   structurellement bien plus faible que les trois précédentes.

### Régional (UEMOA / Afrique)

1. **BCEAO — Banque Centrale des États de l'Afrique de l'Ouest**
   (`bceao.int`), page "Marchés publics et Achats"
   (`.../appels-offres/appels-offres-marches-publics-achats`). **Piège
   rencontré en direct** : ne pas confondre avec `bceao.int/fr/appels-offres`
   — cette dernière est une page DISTINCTE consacrée aux adjudications
   MONÉTAIRES (émissions de Bons/Obligations du Trésor, injections de
   liquidité hebdomadaires), sans aucun rapport avec un achat de biens/
   services ; la bonne page a été retrouvée via son lien de pied de page.
   HTML rendu côté serveur (`requests` seul suffit), robots.txt Drupal
   standard sans règle bloquante, mentions légales sans clause anti-scraping
   (seule restriction : republication de Documents de travail/Études signés,
   sans rapport avec cette liste d'avis). **~1 310 avis au total, ~1
   publié/jour, réellement actif** (dernier avis vu le jour même du test).
   Chaque avis a sa propre page détail avec, la plupart du temps, un **lien
   PDF direct** vers le dossier (DAO/cahier des charges) — pas de formulaire
   de demande comme PMMP/ONDA. Portée **régionale** (UEMOA : Bénin, Burkina
   Faso, Côte d'Ivoire, Guinée-Bissau, Mali, Niger, Sénégal, Togo), pas
   seulement Côte d'Ivoire — tous les avis sont collectés (`Pays` = "UEMOA
   (BCEAO)"), un fournisseur basé à Abidjan pouvant candidater sur n'importe
   quel avis BCEAO quel que soit le pays d'exécution physique.
2. **BAD/AfDB — Banque Africaine de Développement**, siège à Abidjan — deux
   flux RSS distincts (`collector_bad.py`), zéro inscription, zéro scraping
   HTML (juste du XML) :
   - **"Project Procurement"** (`afdb.org/en/projects-and-operations/procurement.xml`)
     : avis liés aux projets financés par la BAD dans ses pays membres
     (types AMI/EOI/IFB/PPM/GPN). **Constaté empiriquement : flux
     PANAFRICAIN**, pas Côte d'Ivoire uniquement (sur 20 avis récents à un
     instant donné, aucun n'était ivoirien — Togo, Bénin, Nigeria, Mali,
     Sénégal, Cabo Verde...). Titre structuré `TYPE - Pays - Description`,
     ce qui permet un filtrage fiable par pays côté client
     (`--bad-country-filter`, "Côte d'Ivoire" par défaut) plutôt qu'une
     recherche de sous-chaîne dans tout le texte.
   - **"Corporate Procurement"** (`.../corporate-procurement/procurement-notices/current-solicitations.xml`)
     : achats internes de la BAD elle-même (informatique, facilities,
     télécoms...), tous bureaux confondus dans le monde — y compris son
     siège à Abidjan. **Contenu réellement pertinent constaté** :
     "Static Application Security (SAST) and Software Composition Analysis
     (SCA) Solution", "Security Service Edge (SSE) Solution", "High Speed
     Internet Connectivity Solution", et un avis portant explicitement sur
     la "cité BAD à Abidjan". Pas de filtre pays ici : un achat pour
     n'importe quel bureau BAD reste ouvert à un prestataire basé à Abidjan.
   - **Piège rencontré en direct** : l'URL "Corporate Solicitations" trouvée
     initialement (`.../corporate-procurement/current-solicitations.xml`,
     sans le segment `procurement-notices`) est **morte (404)** — la bonne
     URL a été retrouvée via la page officielle `afdb.org/en/rss-feeds`.
   - **Dates limites absentes du flux RSS lui-même** (le `<description>` ne
     fait que répéter le titre) : récupérées en enrichissement depuis la
     page détail de chaque avis candidat (champ
     `field-name-field-procurement-end-date`, avec un attribut `content`
     ISO 8601 directement exploitable) — les avis dont la vraie date limite
     s'avère dépassée/trop proche sont réévalués et écartés après coup.

### Identifiée mais pas encore construite

- **UNGM — UN Global Marketplace** (`ungm.org`) : **confirmée viable, pas
  encore intégrée.** Vérifié en direct : `/Public/Notice` affiche 1 717
  avis réels sans connexion (statut 200, pas de mur de connexion dans le
  HTML), `robots.txt` n'interdit pas cette page, les Conditions
  d'utilisation ne contiennent aucune clause anti-scraping. Un vrai filtre
  "Beneficiary country or territory" existe côté serveur, avec "Côte
  d'Ivoire" comme option explicite (`<select id="selNoticeCountry">`,
  valeur "2341"), plus un filtre "Type of opportunity" (Request for EOI/
  RFP/RFQ, Invitation to bid, Call for individual consultants...).
  **Ce qui reste à faire** : le moteur de recherche est un widget JS
  personnalisé (picker caché derrière un `<select>` natif non visible,
  déclenchement de la recherche non élucidé lors d'un premier essai
  Playwright) — l'automatiser proprement demande un travail d'itération
  comparable à celui qu'a demandé PMMP au départ, pas un simple parsing
  HTML comme BCEAO. Alternative : l'API OData v4 (structurée, plus stable
  qu'un scraping de widget JS) nécessite une inscription développeur
  gratuite sur `developer.ungm.org` — à faire par l'utilisateur lui-même
  (compte lié à son identité/entreprise), pas automatisable depuis ce
  pipeline.

## Sources évaluées et écartées

- **PPM Côte d'Ivoire (Plans de Passation des Marchés)** — construit puis
  **retiré du pipeline** (demandé explicitement, 05/08/2026). Deux raisons
  cumulatives : (1) **contenu majoritairement hors du domaine métier
  réel**, constaté en direct sur les avis effectivement écrits dans l'Excel
  — "Acquisition d'un camion **benne**...", "Réalisation de cinq
  **forages** équipés de pompes...", "Révision générale de **l'électricité**
  de l'Hôtel de Ville", "Acquisition de **mobiliers** (tables-bancs,
  bureaux...)" — aucun pré-filtre par mots-clés IT n'existait côté
  collecteur (contrairement à DGMP-CI/BCEAO/BAD), et plusieurs de ces avis
  contiennent pourtant "Acquisition"/"Fourniture" (verbes d'exclusion
  attendus) sans que l'objet acquis (camion, benne, mobilier, bureau,
  plaques...) soit reconnu par `MOTS_OBJET_MATERIEL` — liste construite au
  fil des sources IT, jamais pensée pour couvrir l'intégralité des achats
  publics génériques d'un plan de passation tous secteurs confondus. (2)
  **Dates structurellement anciennes** : déjà documenté avant retrait — la
  "date prévisionnelle" du PPM est la date CIBLE de publication de l'avis
  fixée par l'acheteur, pas la date d'édition du document ; le document le
  plus récent constaté a un délai médian de 90 jours entre cette date cible
  et sa propre publication, 91% des lignes étant déjà en retard sur leur
  propre calendrier prévisionnel au moment où on les lit. Combiné au point
  (1), corriger le filtrage n'aurait résolu qu'une partie du problème.
  `collector_ci_ppm.py` reste sur disque (fonctionnel, testé) mais n'est
  plus importé ni appelé par `run_collect.py` — aucun flag pour le
  réactiver, contrairement au choix fait pour ONDA (ici, aucune des deux
  raisons du retrait n'est un simple réglage de mots-clés à corriger).
- **SIGOMAP** (`sigomap.gouv.ci`) — devenu le portail transactionnel
  obligatoire (dépôt d'offres) depuis le 01/11/2023 en Côte d'Ivoire.
  Techniquement, c'est une SPA Next.js dont le backend REST
  (`backend.sigomap.gouv.ci`) répond systématiquement 403 sans session
  authentifiée. La page d'accueil présente "l'affichage de tous les avis
  d'appel d'offres en temps réel" comme une fonctionnalité de **l'espace
  entreprise connecté** — non accessible sans compte "opérateur économique"
  (numéro de contribuable ivoirien requis à l'inscription). Non intégré :
  nécessiterait des identifiants d'entreprise réels fournis par
  l'utilisateur (jamais en dur dans le code, via `.env`) — à activer sur
  demande explicite si un compte est disponible.
- **AfriTenders** (`afritenders.com`) — agrégateur privé (SaaS, société
  YOWIT SARL) qui republie notamment des avis DGMP/ANRMP avec une fraîcheur
  bien meilleure que la page DGMP brute. **Ses CGU (`/terms`) interdisent
  explicitement l'automatisation de l'accès au site ("scraping") sans
  autorisation** — écarté pour cette raison contractuelle, indépendamment de
  la faisabilité technique (`robots.txt` du site l'autoriserait
  techniquement). Décision alignée sur le principe déjà appliqué côté France
  (agrégateurs privés non intégrés sans accès contractuel clair).
- **africatenders.net**, **wuripay.com** (Côte d'Ivoire), **aljady.ma**,
  **datao.ma** (Maroc) — CGU vérifiées individuellement, toutes interdisent
  explicitement l'automatisation : africatenders.net et datao.ma
  interdisent "l'utilisation de systèmes automatisés ou de logiciels
  (robots, 'scrapers')" en toutes lettres ; aljady.ma protège sa "base de
  données" contre toute reproduction sans autorisation écrite ;
  wuripay.com bloque nommément une liste de crawlers IA dans son
  `robots.txt`, **dont ClaudeBot**. Exclus par principe : ces agrégateurs
  vivent précisément de l'agrégation de cette donnée, ce n'est pas un hasard
  si presque tous la protègent contractuellement.
- **SangoBids** (`sangobids.com`, Sango SARL — Côte d'Ivoire, Cameroun et 7
  autres pays francophones) — agrégateur commercial (agrège DGMP, Banque
  Mondiale, BAD, BCEAO, UNGM ; plans payants, appli iOS). `robots.txt`
  étonnamment permissif (`Allow: /` général, **ClaudeBot et les autres
  crawlers IA explicitement autorisés**, seul `/api/` est interdit), mais
  ses CGU (`/terms`, section 5 "Utilisation acceptable") interdisent
  explicitement : *"Ne pas tenter d'extraire massivement les données
  (scraping) sans autorisation"*. Écarté pour l'instant, mais **pas de la
  même façon qu'AfriTenders** : la clause elle-même invite à demander une
  autorisation ("sans autorisation" sous-entend qu'une autorisation est
  possible), contrairement à AfriTenders qui interdit sans condition. À
  contacter directement (`contact@sangobids.com`) pour explorer un accès
  autorisé/partenariat plutôt qu'à scraper en espérant qu'un faible volume
  échappe à la clause — **ralentir les requêtes ne change pas la nature de
  ce qu'on ferait, seule une autorisation le fait** (même principe déjà
  appliqué à AfriTenders : une clause CGU explicite prime sur la
  permissivité technique/`robots.txt`).
- **ecsinformatique.com**, **cpmaroc.com**, **marchefacile.ma** — aucune
  interdiction explicite trouvée, mais aucune autorisation non plus ;
  exclus par défaut selon le même principe tant qu'une autorisation
  explicite n'est pas confirmée. cpmaroc.com a un profil technique modeste
  (commentaires détaillés dans son `robots.txt` sur ses coûts d'infra) —
  pourrait valoir un contact direct pour demander une autorisation plutôt
  qu'un scraping silencieux.
- **PGPM / PGSPM / PSPM** (Côte d'Ivoire) — anciennes nomenclatures de plans
  de passation (antérieures à 2020) ou plans simplifiés (achats de faible
  montant standardisés) : volontairement ignorés par `collector_ci_ppm.py`,
  hors cible PME de conseil ou obsolètes.
- **ONEE** (`one.ma`, branche Électricité) — page publique sans compte,
  mais **zéro avis IT constaté** : testé sur les catégories "Fournitures" et
  "Grands projets/Travaux" (10 avis chacune, tous du matériel réseau
  électrique ou des travaux de génie électrique), puis recherche par
  mot-clé explicite ("informatique", "système") — "Aucun appel d'offres ne
  répond à votre requête" à chaque fois. Flux structurellement dominé par
  l'équipement électrique, hors cible PME de conseil. Non intégré.
- **ANP — Agence Nationale des Ports** (`anp.org.ma`) — page publique,
  techniquement accessible (vérifié en Playwright, la page est rendue en
  JS), mais son flux "Avis d'appel à la concurrence" est composé
  exclusivement d'**autorisations d'exploitation portuaire** (gardiennage,
  récupération de détritus, concessions commerciales, occupation temporaire
  du domaine public) — une catégorie juridique différente d'un marché
  public classique, et **zéro avis IT** sur l'intégralité des ~30 avis
  visibles (2023-2024). Non intégré : accessible mais hors cible.
- **Marsa Maroc**, **CDG (SAFAKAT)**, **ADM (Autoroutes du Maroc)** — les
  trois ont migré vers un portail d'achats dématérialisé dédié
  (`achats.marsamaroc.co.ma`, `safakat.cdg.ma`, `achats.adm.co.ma`)
  qui exige une **création de compte/connexion pour voir ne serait-ce que la
  liste des avis en cours** — contrairement au PMMP où la consultation est
  publique. Non intégrés par principe (même règle que SIGOMAP : jamais de
  compte créé pour scraper).
- **ONDA — Office National Des Aéroports** (`onda.ma`, `collector_onda.py`)
  — construit puis **désactivé par défaut** (`--include-onda` pour
  l'activer), le code reste dans le projet. Historique complet, pour
  mémoire : la page technique/légale était favorable (publique, sans
  compte, `requests` seul suffit, `robots.txt` non bloquant), et un avis
  réel repéré au lancement ("Formation RED Hat System Administration /
  certification CISCO") semblait démontrer un vrai angle mort du PMMP — sa
  page détail renvoyant vers le PMMP lui-même
  (`EntrepriseDetailsConsultation`, refConsultation=1028954) où sa
  catégorie officielle s'est révélée être *"Services / Services courants /
  Formation du personnel"*, pas `domaineActivite=3.19` (IT) — la seule
  catégorie interrogée par `collector_maroc.py`. **Mais** cet avis
  fondateur s'est lui-même avéré hors scope une fois la règle appliquée
  correctement (dispenser une formation, même sur un sujet IT réel, est un
  métier de centre de formation, pas de conseil/dev/BI — cf. `MOTS_EXCLUSION`
  dans `config.py`). Sans lui, il ne restait aucune preuve concrète de gain :
  **vérifié en direct sur les 14 avis "en cours" de l'ONDA, 0 survivent au
  filtre correctement appliqué** — flux structurellement dominé par
  l'infrastructure aéroportuaire (gardiennage, nettoyage, travaux, entretien
  de bâtiments, équipements), même profil qu'ONEE/ANP ci-dessus. Le
  mécanisme théorique ("un acheteur PMMP peut mal catégoriser un avis
  réellement IT") reste plausible en soi et pourrait un jour concerner un
  autre avis ONDA — d'où le choix de désactiver plutôt que supprimer.

## Limites de couverture

- **BAD/AfDB (et potentiellement UNGM demain) : les mots-clés IT/exclusion
  sont tous en français, or une partie réelle des avis BAD est en anglais
  uniquement.** Constaté en direct sur le flux "Corporate Procurement" :
  "Provision of Cleaning Services..." n'est PAS exclu (aucun équivalent
  anglais de "nettoyage" dans `MOTS_EXCLUSION`), alors qu'un intitulé
  français équivalent le serait. À l'inverse, "Maintenance" s'écrit
  identiquement dans les deux langues, donc "Supply... and Maintenance of a
  Security Service Edge (SSE) Solution" est bien exclu par coïncidence
  orthographique, pas par une vraie couverture bilingue. Risque : sous-
  détection silencieuse côté anglais (jamais de fausse inclusion, juste des
  avis potentiellement pertinents qui restent "à vérifier" au lieu d'être
  mieux triés, ou hors-scope non filtrés faute d'équivalent français).
  Non corrigé pour l'instant — nécessiterait une vraie liste de mots-clés
  anglais, vérifiée avec la même rigueur que la liste française actuelle,
  plutôt qu'une traduction terme à terme rapide.
- **La source DGMP-CI (avis actifs) est presque intégralement un historique
  clos, pas un flux de veille.** Constaté en direct le 03/08/2026 : sur 979
  avis listés, **un seul** avait une date limite non encore dépassée (et
  hors domaine IT). La page ne propose aucun filtre "en cours"/"clôturé"
  côté serveur. `collector_ci.py` reste utile pour capter un avis IT dès sa
  publication si le pipeline tourne fréquemment (ex. quotidien), mais ne
  doit pas être considéré comme une source à haut rendement à lui seul —
  les PPM (prévisionnel) et le PMMP marocain sont les sources à plus fort
  rendement de ce pipeline.
- **PMMP (Maroc)** : la combinaison d'URL `&EnCours&domaineActivite=3.19`
  casse le moteur de recherche côté serveur (page de résultats vide, testé
  en direct) — `collector_maroc.py` interroge donc `domaineActivite=3.19`
  seul (toutes dates) et laisse `filter_classify.is_deadline_too_soon`
  écarter les consultations déjà closes via la date limite réellement
  extraite par ligne. **Le portail limite lui-même la pagination en
  pratique** : sur deux tentatives séparées de parcourir les ~110 pages
  possibles (1100 avis / 10 par page), la pagination s'est arrêtée
  spontanément entre la page 31 et la page 37 (lien "page suivante" disparu,
  ou navigation en échec sans message d'erreur) — probable limite de
  session, pas un bug du collecteur (qui journalise désormais clairement
  tout arrêt anticipé, avec le nombre d'avis déjà collectés). Dans les deux
  cas, les mêmes 12 avis finaux ont été retenus après filtrage — rien
  d'important ne semble se trouver au-delà de la page ~35 à ce jour, mais
  ce n'est pas garanti pour toute future collecte.
- **PPS (Maroc, programme prévisionnel)** : rendement structurellement
  **faible**, constaté en direct. Sur un premier échantillon des 15
  documents les plus récents, **0 sur 15** contenaient du texte extractible
  — tous scannés, et publiés par de petites entités (communes rurales,
  directions provinciales d'agriculture) peu susceptibles d'avoir un projet
  IT. Un échantillon élargi à 300 documents a en outre déclenché plusieurs
  `Read timed out` côté serveur sous charge soutenue, malgré un délai entre
  requêtes (`config.REQUEST_DELAY_SECONDS`) — signe que ce portail supporte
  mal un grand nombre de téléchargements séquentiels. **Recommandation :
  garder `--maroc-pps-max-documents` à sa valeur par défaut (30) ou en
  dessous**, et considérer cette source comme exploratoire/complémentaire,
  pas comme un flux à haut rendement comme le PMMP principal ou le PPM
  ivoirien. Aucun document sans texte extractible n'est jamais classé
  "hors IT" par défaut — il est simplement absent du résultat, sans
  affirmation dans un sens ou dans l'autre.
- **Bugs de classification corrigés en cours de route, à connaître si vous
  retrouvez d'anciennes données** : (1) le nom de l'ACHETEUR était inclus
  dans le texte analysé, faisant passer par exemple "Acquisition de
  véhicules pour la SNDI" en "IT confirmé" uniquement parce que "SNDI"
  signifie "Société Nationale de Développement **Informatique**" — corrigé,
  seul l'objet est analysé désormais. (2) le mot-clé d'exclusion BTP
  "voirie" matchait par sous-chaîne à l'intérieur de "ivoirienne"/"ivoirien"
  — toute annonce mentionnant l'administration ou l'État ivoirien perdait un
  point à tort ; corrigé par une recherche par limite de mot
  (`filter_classify._contains_keyword`) plutôt que par sous-chaîne brute.
  (3) **Constaté à l'intégration de l'ONDA** : contrairement à DGMP-CI (déjà
  pré-filtré par mots-clés côté collecteur) et au PMMP (déjà pré-filtré par
  catégorie serveur `domaineActivite=3.19`), la page ONDA liste TOUS ses
  avis sans aucun filtre de domaine — le filet de sécurité "aucun signal ->
  à vérifier" de `classify_domain` (pensé pour un flux déjà restreint à
  l'IT) laissait donc passer des prestations génériques sans rapport avec
  l'IT (gardiennage, nettoyage, collecte de déchets, climatisation) qui
  n'auraient jamais atteint ce stade sur les deux autres sources ; corrigé
  en ajoutant ces catégories à `MOTS_EXCLUSION`. Piège rencontré au passage :
  une locution figée comme "collecte des déchets" ne matchait pas le
  libellé réel "collecte des **débris**, des déchets et des ordures"
  (énumération qui casse la contiguïté) — d'où l'usage de mots isolés
  plutôt que de locutions complètes pour ces termes précis.
  (4) **Constaté en direct sur des avis PMMP réels** (tous classés "à
  vérifier" à tort avant correctif) : "Achat et production de capsules
  vidéo" (production audiovisuelle — généralisation de captation/
  retransmission), "L'abonnement à un service de Supervision..." (un
  abonnement est un engagement récurrent de type "run", même logique que
  hébergement/maintenance), "Assistance à l'externalisation... vers un
  datacenter souverain" (sujet d'infrastructure/hosting, même en tournure
  AMOA), et "Renouvellement **des** licences" qui ne matchait aucune des
  deux variantes existantes de `MOTS_ACQUISITION` (toutes deux avec l'article
  singulier "**de** licence(s)") — corrigé en ajoutant "abonnement",
  "datacenter"/"data center", "capsule(s) vidéo", "production vidéo"/
  "production audiovisuelle" à `MOTS_EXCLUSION`, et "renouvellement des
  licences" à `MOTS_ACQUISITION`.
- **La classification IA du domaine** est reprise à l'identique du pipeline
  France (mêmes règles, même prudence sur les termes ambigus AMOA/maîtrise
  d'ouvrage) — voir `APPEL_OFFRES/README.md` pour le détail du raisonnement.
  Sans signal CPV disponible pour ces sources (contrairement au BOAMP), la
  classification repose uniquement sur les mots-clés de l'objet.
- **ONDA (Maroc)** : risque théorique de doublon avec le PMMP si un même
  avis ONDA était un jour aussi tagué `domaineActivite=3.19` sur le PMMP (les
  deux collecteurs généreraient alors deux lignes distinctes, préfixes
  d'ID différents — `MA-{référence PMMP}` vs `MA-ONDA-{référence ONDA}` — le
  dédoublonnage par ID ne les fusionnerait pas). Non constaté en pratique à
  ce jour (aucun chevauchement trouvé lors de l'intégration), documenté par
  prudence plutôt que traité par une logique de fusion non testée. Par
  ailleurs, la page ONDA ne liste que les avis "en cours" (pas de
  pagination constatée sur ~14 avis) — un volume qui dépasserait ce qui
  tient sur cette page unique changerait potentiellement ce constat, à
  surveiller si le nombre d'avis ONDA simultanés augmente significativement.
- **Aucune exhaustivité n'est garantie ni implicite.** Ce pipeline est un
  outil d'aide à la détection, pas un système de veille certifié complet.

## Respect des CGU et de robots.txt

Mêmes principes que le pipeline France : `USER_AGENT` explicite identifiant
l'outil, délai minimal entre requêtes (`config.REQUEST_DELAY_SECONDS`,
appliqué explicitement entre chaque téléchargement de document PPS),
aucune page d'authentification jamais contournée (SIGOMAP, nécessitant un
compte, n'a pas été scrapé au-delà de ce qui est public). Les sources dont
les CGU interdisent explicitement l'automatisation (AfriTenders) sont
exclues par principe, indépendamment de la faisabilité technique. Le PPS
marocain ayant montré des signes de ralentissement/timeouts sous charge
séquentielle soutenue (cf. Limites de couverture), `--maroc-pps-max-documents`
doit rester modéré par défaut plutôt que d'être poussé vers l'exhaustivité.

## Colonnes de l'Excel

Onglet **"Appels d'offres"** (avis actifs DGMP-CI + PMMP) :
`Référence/ID | Pays | Source | Référence | Objet | Acheteur | Domaine |
Type de marché | Procédure | Lieu d'exécution | Devise | Montant estimé |
Caution provisoire | Date publication | Date limite | Lien avis | Lien DCE |
Date de collecte`

"Lien avis" et "Lien DCE" sont des hyperliens directement cliquables (pas du
texte brut). "Montant estimé"/"Caution provisoire" ne sont renseignés que
pour les sources marocaines (PMMP, ONDA) — DGMP-CI n'expose pas ce chiffre
sur sa page publique. Pour l'ONDA, ces deux champs sont fréquemment vides
("non précisé") : constaté en direct, l'ONDA affiche un placeholder "_"
plutôt qu'un chiffre pour beaucoup de ses avis — jamais interprété comme un
montant nul.

Onglet **"Plans prévisionnels"** (PPS Maroc — le PPM Côte d'Ivoire a été
retiré du pipeline, cf. Sources évaluées et écartées) :
`Référence/ID | Pays | Source | Ministère | Autorité contractante | Objet |
Domaine | Bailleur | Type de marché | Mode de passation | Devise | Montant
estimé | Remarque montant | Date prévisionnelle publication | Lien source |
Date de collecte`

Pour les lignes PPS (Maroc), "Objet" contient un extrait de texte autour du
mot-clé IT trouvé dans le document (pas un objet structuré), et "Lien
source" pointe directement vers le PDF d'origine à consulter manuellement.

## Modifications manuelles dans l'Excel

Demandé explicitement : vos modifications manuelles (surlignage, suppression
de ligne) doivent survivre à la prochaine collecte, pas être écrasées ou
réapparaître silencieusement. Deux mécanismes dans `excel_writer.py` :

1. **Surligner une ligne la protège définitivement.** Dès qu'une ligne porte
   un remplissage de cellule (n'importe quelle couleur, n'importe quelle
   colonne), le pipeline ne modifie plus jamais ses valeurs, et ne la
   supprime plus jamais automatiquement — même si une collecte ultérieure la
   reclasserait "hors IT" ou ne la retrouve plus dans la source. Aucune
   colonne ni convention supplémentaire à apprendre : surligner suffit.
2. **Supprimer une ligne ne la fait plus réapparaître.** Un registre
   persistant par onglet (`data/_ids_geres_<onglet>.json`, à ne pas
   supprimer) mémorise tous les ID déjà proposés par le pipeline. Si un ID
   connu disparaît de l'onglet (vous l'avez supprimée) mais reste un
   candidat valide côté source, il n'est plus réinjecté automatiquement.
3. **Les lignes obsolètes non protégées sont désormais retirées
   automatiquement** (et non plus laissées à traîner indéfiniment) : quand
   une collecte complète d'une source ne retrouve plus un avis qui existait
   avant (délai dépassé, reclassé hors IT, disparu de la source...), sa
   ligne est retirée de l'Excel — sauf si elle est surlignée (point 1). Le
   retrait n'utilise jamais `ws.delete_rows()` (bug connu, cf. plus haut
   dans ce document) : l'onglet est reconstruit dans le même classeur, en
   copiant explicitement chaque style (police, remplissage, bordure,
   hyperlien) plutôt que par simple suppression de ligne.

## Tests

```bash
pytest -q
```

148 tests, tous hors-ligne (aucun appel réseau) : classification de domaine
(dont les bugs acheteur/voirie-ivoirienne verrouillés par des tests de
non-régression), parsing HTML DGMP-CI, extraction PPM, normalisation PMMP
(dont la déduplication objet/lieu — bug d'info-bulle PRADO), extraction
montant/caution, extraction PPS, parsing/normalisation ONDA (dont les
formats de référence variables et le format de date en toutes lettres),
parsing/normalisation BCEAO (dont le décodage d'entités HTML et la
distinction section "En cours"/"Clos"), parsing/normalisation des deux flux
RSS BAD (dont le filtrage pays insensible aux accents et le découpage de
titre structuré), dédoublonnage et hyperliens Excel, protection des lignes
surlignées/supprimées manuellement et nettoyage des lignes obsolètes.
