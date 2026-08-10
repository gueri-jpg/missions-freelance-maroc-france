"""Configuration centrale du pipeline de veille des appels d'offres IT —
Côte d'Ivoire (DGMP) et Maroc (PMMP) — CFConsulting.

Même logique que le pipeline France (`APPEL_OFFRES/config.py`) : toutes les
valeurs "métier" vivent ici pour que les collecteurs/filtres restent des
modules sans état métier codé en dur. Les listes de mots-clés IT sont
reprises à l'identique du pipeline France (même définition du domaine
cible), les seuils PME sont adaptés à la devise locale de chaque pays.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
EXCEL_PATH = DATA_DIR / "veille_appels_offres_afrique.xlsx"

for _d in (DATA_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Seuils métier (PME de conseil IT)
# ---------------------------------------------------------------------------
# Aucun seuil de montant maximal appliqué ici (contrairement à la France/
# BOAMP) : ni DGMP-CI ni PMMP n'exposent de montant estimé exploitable dans
# les sources collectées par ce pipeline (colonne absente/non renseignée sur
# les pages listées) — un seuil qu'on ne peut jamais évaluer serait un filtre
# mort. À réintroduire si une source avec montant fiable est ajoutée.

# Délai minimal (jours) entre aujourd'hui et la date limite de soumission
# pour qu'un avis reste dans l'Excel.
DELAI_MIN_SOUMISSION_JOURS = 7

# ---------------------------------------------------------------------------
# Mots-clés IT — repris à l'identique de APPEL_OFFRES/config.py (même
# définition du domaine cible, indépendante du pays). Voir ce fichier pour
# le détail du raisonnement derrière chaque liste.
#
# IMPORTANT : ne PAS ajouter de terme générique isolé ("informatique",
# "numérisation", "digitalisation"...) à MOTS_CLES_IT_FORTS, même si tentant
# pour élargir le rappel sur les libellés africains. Constaté en direct :
# un ajout de "informatique" seul faisait classer "IT confirmé" des annonces
# comme "Maintenance du parc informatique" ou "Acquisition de matériels
# informatiques" — exactement les acquisitions/fournitures/maintenances hors
# cible PME de conseil. Ces termes génériques restent dans
# MOTS_CLES_CONTEXTE_IT (utile seulement en renfort d'un terme ambigu type
# AMOA), jamais seuls dans FORTS.
# ---------------------------------------------------------------------------
MOTS_CLES_IT_FORTS = [
    "power bi", "business intelligence", "décisionnel", "decisionnel",
    "dataviz", "data visualization", "visualisation de données",
    "talend", "etl",
    "développement logiciel", "developpement logiciel",
    "développement applicatif", "developpement applicatif",
    "développement web", "developpement web",
    "développement mobile", "developpement mobile",
    "développement informatique", "developpement informatique",
    "logiciel", "applicatif", "progiciel",
    "système d'information", "systeme d'information", "système d'information",
    "sirh",
    "site internet", "site web", "application mobile",
    "base de données", "base de donnees",
    "cybersécurité", "cybersecurite",
    "conseil en systèmes d'information",
    # Équivalents anglais — demandé explicitement : les sources régionales/
    # panafricaines (BAD, potentiellement UNGM) publient une partie réelle de
    # leur contenu en anglais uniquement (constaté en direct sur le flux BAD
    # "Corporate Procurement" : "Static Application Security (SAST)...",
    # "Security Service Edge (SSE) Solution"), que la liste précédente,
    # entièrement française, ne pouvait jamais confirmer comme IT — elle ne
    # faisait que les laisser passer par le filet "à vérifier", et ne les
    # empêchait pas non plus d'être noyés dans du bruit sans aucun pré-filtre
    # de rappel (cf. MOTS_CLES_IT plus bas). Liste volontairement limitée aux
    # équivalents directs des termes forts déjà présents, pas une traduction
    # exhaustive de tout MOTS_EXCLUSION (cf. limite documentée au README).
    "web development", "web application development",
    "mobile application development", "mobile app development",
    "software development", "information system",
    "cybersecurity", "cyber security",
    "it consulting", "information technology consulting",
]

MOTS_CLES_AMBIGUS = [
    "amoa", "amo si", "assistance à maîtrise d'ouvrage",
    "assistance a maitrise d'ouvrage", "maîtrise d'ouvrage", "maitrise d'ouvrage",
    # "AMO"/"PMO" seuls — demandé explicitement (périmètre PME : "AMO/AMOA/
    # PMO IT"). Comme "amoa", ce sont des fonctions transversales utilisées
    # hors IT (AMO travaux/bâtiment, PMO générique de programme) : rangés en
    # AMBIGUS, jamais suffisants seuls pour confirmer l'IT (il faut un terme
    # de contexte IT co-présent, cf. _has_it_keyword).
    "amo", "pmo", "project management office",
]

MOTS_CLES_CONTEXTE_IT = [
    "système d'information", "systeme d'information", "système d'information",
    "informatique", "numérique", "numerique", "digital",
    "logiciel", "applicatif", "sirh", "si ",
    "information system", "information technology",
]

MOTS_CLES_IT = MOTS_CLES_IT_FORTS + MOTS_CLES_AMBIGUS

MOTS_EXCLUSION = [
    "bâtiment", "batiment", "voirie", "vrd", "réseaux secs", "reseaux secs",
    "assainissement", "urbanisme", "paysage", "espaces verts",
    "construction", "réhabilitation", "rehabilitation",
    "démolition", "demolition", "travaux", "gros oeuvre", "gros œuvre",
    "génie civil", "genie civil",
    "aménagement urbain", "amenagement urbain",
    "maîtrise d'oeuvre", "maitrise d'oeuvre", "maîtrise d'œuvre",
    "thermique", "chauffage", "voierie",
    "signalisation routière", "signalisation routiere",
    "éclairage public", "eclairage public",
    "écologue", "ecologue", "écologique", "ecologique",
    "mesures compensatoires", "mesure compensatoire",
    "biodiversité", "biodiversite", "milieux naturels",
    "mise en accessibilité", "mise en accessibilite",
    "accessibilité pmr", "accessibilite pmr",
    "personnes à mobilité réduite", "personnes a mobilite reduite",
    "signalétique", "signaletique", "mobilier urbain",
    "infogérance", "infogerance", "tierce maintenance applicative",
    "tma", "maintien en condition opérationnelle", "mco",
    "contrat de maintenance", "maintenance corrective", "maintenance évolutive",
    "maintenance corrective et évolutive", "maintenance applicative",
    "maintenance et support", "reprise de la maintenance",
    # Terme nu (au-delà des locutions ci-dessus, absentes de APPEL_OFFRES/
    # config.py) : demandé explicitement — les annonces de "simple
    # maintenance" (parc informatique, matériel, équipements...) sans volet
    # projet/développement doivent être écartées. Un terme IT fort présent en
    # même temps (ex. "développement et maintenance évolutive d'une
    # application") fait basculer la ligne en "à vérifier", jamais en
    # exclusion dure — cf. classify_domain.
    "maintenance", "entretien",
    # "Hébergement"/"prestation d'hébergement" — demandé explicitement :
    # service d'exploitation ("run"), pas une prestation de conseil/dev,
    # même logique que maintenance/infogérance ci-dessus. Un terme IT fort
    # co-présent (ex. "Hébergement et Infogérance ... du Site Web") fait
    # basculer en "à vérifier", jamais en exclusion dure.
    "hébergement", "hebergement",
    # Domaines hors périmètre récurrents constatés en collecte réelle
    # (Maroc, catégorie officielle "Services de technologies de
    # l'information" mais objet réel sans rapport) : gestion associative/
    # culturelle, captation et diffusion audiovisuelle. Un terme IT fort
    # co-présent fait basculer en "à vérifier", jamais en exclusion dure.
    "centre culturel", "épanouissement artistique", "epanouissement artistique",
    "captation", "retransmission",
    # Constaté en direct sur l'ONDA (05/08/2026) : contrairement à DGMP-CI
    # (déjà pré-filtré par mots-clés IT côté collecteur) et au PMMP (déjà
    # pré-filtré par catégorie serveur domaineActivite=3.19), la page ONDA
    # liste TOUS ses avis sans aucun filtre de domaine — le filet de sécurité
    # "aucun signal -> à vérifier" de classify_domain (pensé pour un flux déjà
    # restreint à l'IT) laisse donc passer en "à vérifier" des prestations de
    # service génériques sans aucun rapport avec l'IT (gardiennage, nettoyage,
    # collecte de déchets, climatisation), qui n'auraient jamais atteint ce
    # stade sur les deux autres sources. Comme pour maintenance/hébergement
    # ci-dessus, un terme IT fort co-présent fait toujours basculer en "à
    # vérifier", jamais en exclusion dure (ex. "nettoyage et dédoublonnage de
    # la base de données" reste "à vérifier" grâce à "base de données").
    # Mots isolés plutôt que locutions complètes : constaté en direct, "collecte
    # des déchets" (locution figée) ne matchait pas le libellé réel "collecte
    # des débris, des déchets et des ordures" (énumération qui casse la
    # contiguïté de la phrase) — corrigé en mots isolés, sans risque de faux
    # positif IT (aucun sens technique alternatif pour "déchets"/"ordures").
    "gardiennage", "nettoyage", "déchets", "ordures", "climatisation",
    # "Formation" — demandé explicitement : dispenser une formation/
    # certification (même sur un sujet IT réel, ex. "Formation RED Hat
    # System Administration"/"certification CISCO") est un métier de centre
    # de formation, pas du développement web/mobile/BI/conseil — hors scope
    # même quand le sujet est techniquement de l'IT, même logique que
    # maintenance/hébergement ci-dessus (métier différent, pas juste un
    # thème adjacent). Mot isolé plutôt que locution : le "s?" optionnel
    # standard de _contains_keyword couvre "formations". Sans risque de faux
    # positif par sous-chaîne : "\bformation\b" ne matche PAS à l'intérieur
    # de "information"/"système d'information" (pas de limite de mot entre
    # "in" et "formation", vérifié en direct). Un terme IT fort co-présent
    # (ex. "Développement d'un module e-learning de formation") fait
    # toujours basculer en "à vérifier", jamais en exclusion dure.
    "formation",
    # Constaté en direct sur le PMMP (avis réels, tous classés "à vérifier"
    # à tort avant correctif) :
    # - "abonnement" : un abonnement à un service (même de supervision/
    #   sécurité SI) est un engagement récurrent de type "run", pas une
    #   mission de conseil/dev/BI — même logique que hébergement/maintenance.
    # - "datacenter"/"data center" : externaliser/héberger vers un
    #   datacenter est un sujet d'infrastructure/hosting, pas de conseil
    #   applicatif — même logique que hébergement, même en tournure
    #   "Assistance à l'externalisation... vers un datacenter souverain".
    #   IMPORTANT — demandé explicitement : le mot ISOLÉ "data" (programme
    #   Data, Data Lake, Big Data, Data Scientist...) ne doit JAMAIS être
    #   exclu par ce terme — "datacenter"/"data center" sont des mots/
    #   locutions COMPLETS, la limite de mot de _contains_keyword empêche
    #   tout match par sous-chaîne sur "data" seul (vérifié en direct, cf.
    #   test_classify_domain_datacenter_ne_matche_pas_projet_data).
    # - "capsule vidéo"/"capsules vidéo", "production vidéo",
    #   "production audiovisuelle" : production de contenu audiovisuel,
    #   même généralisation que captation/retransmission ci-dessus. Mots
    #   isolés/locutions dédoublées (singulier ET pluriel du premier mot)
    #   pour la même raison que déchets/ordures : le "s?" de
    #   _contains_keyword ne couvre que le DERNIER mot d'une locution.
    "abonnement", "datacenter", "data center",
    "capsule vidéo", "capsules vidéo", "production vidéo", "production audiovisuelle",
]

MOTS_ACQUISITION = [
    "acquisition", "acquérir", "acquerir", "achat", "acheter",
    "renouvellement de licence", "renouvellement de licences",
    # Constaté en direct (PMMP) : "renouvellement DES licences" (article
    # pluriel) ne matchait aucune des deux variantes ci-dessus (article
    # singulier "de") — locution complète, le "s?" de _contains_keyword ne
    # couvre que le dernier mot, pas l'article en tête de phrase.
    "renouvellement des licences",
    # "souscription des licences Microsoft" observé en direct (Maroc) —
    # souscrire des licences est un achat, pas une prestation de conseil.
    "souscription",
    # "Location" — demandé explicitement : louer du matériel/une
    # plateforme est un achat temporaire, pas une prestation de conseil.
    "location",
]

MOTS_OBJET_MATERIEL = [
    "logiciel", "licence", "licences", "matériel", "materiel",
    "équipement", "equipement", "progiciel", "solution logicielle",
    # Ajouts constatés en direct (Maroc/CI) : "Acquisition d'une plateforme
    # générative...", "Acquisition ... d'une infrastructure d'IA (on-premise)",
    # "Acquisition de véhicules" — l'objet matériel n'est pas toujours nommé
    # "logiciel"/"licence" explicitement, ces termes couvrent les libellés
    # réels rencontrés qui décrivent un bien acheté, pas une prestation.
    "plateforme", "infrastructure", "véhicule", "vehicule",
    "véhicules", "vehicules", "solution",
]

MOTS_FOURNITURE = ["fourniture", "fournitures"]
FOURNITURE_SERVICE_EXCEPTIONS = [
    "fourniture de prestations", "fournitures de prestations",
    "fourniture des prestations", "fourniture de service", "fourniture de services",
]

MOTS_EXCLUSION_FORTE = [
    "fourniture, installation et maintenance",
]

# ---------------------------------------------------------------------------
# Réseau — respect des CGU des plateformes / robots.txt
# ---------------------------------------------------------------------------
USER_AGENT = "CFConsulting-VeilleAO-Afrique/1.0 (usage raisonnable ; contact: rgueriatou@gmail.com)"
HTTP_TIMEOUT = 30
REQUEST_DELAY_SECONDS = 1.5

# ---------------------------------------------------------------------------
# Sources officielles — Côte d'Ivoire
# ---------------------------------------------------------------------------
# DGMP (Direction Générale des Marchés Publics) — site institutionnel PHP,
# statique côté serveur, sans compte requis. Liste "Avis d'appels d'offres"
# en cours (~980 lignes constatées, dates jusqu'en 2026 -> activement tenue
# à jour), robots.txt absent (404) = aucune règle explicite trouvée.
# Distinct de SIGOMAP (sigomap.gouv.ci), portail transactionnel (dépôt
# d'offres) devenu obligatoire depuis le 01/11/2023 pour PARTICIPER, mais qui
# n'expose la liste des avis qu'à un compte "opérateur économique" connecté
# (SPA Next.js, backend REST protégé) — non exploitable sans compte, cf.
# README pour le détail du test technique.
CI_DGMP_BASE_URL = "https://marchespublics.ci"
CI_DGMP_APPELS_OFFRES_URL = "https://marchespublics.ci/appel_offre"

# Plans de Passation des Marchés (PPM) — programme prévisionnel annuel des
# achats publics, publié par trimestre cumulatif (PDF). Équivalent ivoirien
# d'APProch (France) : projets ANNONCÉS avant publication formelle de l'avis,
# non exhaustifs par nature, à traiter comme "à confirmer" et non comme un
# avis ferme. Distinct des PGPM/PGSPM (anciens plans généraux, nomenclature
# antérieure à 2020) volontairement ignorés ici.
CI_DGMP_PLAN_PASSATION_URL = "https://marchespublics.ci/plan_passation"
# Ne télécharge que les PPM des N dernières années civiles (les documents
# plus anciens sont sans intérêt pour une veille d'opportunités à venir).
CI_PPM_ANNEES_A_COLLECTER = 1

# ---------------------------------------------------------------------------
# Source complémentaire — BCEAO (Banque Centrale des États de l'Afrique de
# l'Ouest), institution régionale UEMOA (Bénin, Burkina Faso, Côte d'Ivoire,
# Guinée-Bissau, Mali, Niger, Sénégal, Togo).
# ---------------------------------------------------------------------------
# IMPORTANT — à ne pas confondre avec `bceao.int/fr/appels-offres` (page
# distincte, constaté en direct 05/08/2026 : ce sont des adjudications
# MONÉTAIRES — émissions de Bons/Obligations du Trésor, injections de
# liquidité hebdomadaires — sans aucun rapport avec un achat de biens/
# services). La bonne page est "Marchés publics et Achats"
# (`.../appels-offres-marches-publics-achats`), trouvée via son lien de pied
# de page. Vérifié en direct : HTML rendu côté serveur (`requests` seul
# suffit), robots.txt Drupal standard sans règle bloquante, mentions légales
# sans clause anti-scraping (seule restriction : republication de documents
# de recherche signés — Documents de travail, Études — sans rapport avec
# cette liste d'avis). ~1 avis publié par jour en moyenne, réellement actif
# (dernier avis vu le jour même du test). Chaque avis a sa propre page
# détail avec, la plupart du temps, un lien PDF direct vers le dossier
# (DAO/cahier des charges) — pas de formulaire de demande comme PMMP/ONDA.
#
# Portée RÉGIONALE (UEMOA), pas seulement Côte d'Ivoire : un fournisseur basé
# à Abidjan peut candidater sur n'importe quel avis BCEAO quel que soit le
# pays d'exécution physique (siège à Dakar, avis vus pour le Bénin, le
# Burkina, le Togo, le Mali...). Tous les avis sont donc collectés, avec
# "Pays" = "UEMOA (BCEAO)" plutôt que "Côte d'Ivoire" — pas un pays unique.
BCEAO_ACHATS_URL = "https://www.bceao.int/fr/appels-offres/appels-offres-marches-publics-achats"

# ---------------------------------------------------------------------------
# Source complémentaire — BAD/AfDB (Banque Africaine de Développement),
# siège à Abidjan. Deux flux RSS distincts, zéro inscription, zéro scraping
# HTML (juste du XML).
# ---------------------------------------------------------------------------
# IMPORTANT — l'URL "Corporate Solicitations" trouvée initialement
# (.../corporate-procurement/current-solicitations.xml) est MORTE (404,
# vérifié en direct) : le vrai chemin inclut un segment "procurement-notices"
# supplémentaire, trouvé via la page officielle afdb.org/en/rss-feeds.
#
# 1) "Project Procurement" : avis liés aux projets financés par la BAD dans
#    ses pays membres (AMI/EOI/IFB/PPM/GPN). Vérifié en direct : flux PANAFRICAIN,
#    pas Côte d'Ivoire uniquement (sur 20 avis récents constatés, aucun n'était
#    ivoirien un jour donné — Togo, Bénin, Nigeria, Mali, Sénégal, Cabo Verde...).
#    Titres au format structuré "TYPE - Pays - Description" (ex. "AMI - Togo -
#    Élaboration de rapports..."), ce qui permet un filtrage fiable par pays
#    côté client plutôt qu'une recherche de sous-chaîne dans tout le texte.
BAD_PROJECT_PROCUREMENT_RSS_URL = "https://www.afdb.org/en/projects-and-operations/procurement.xml"
# 2) "Corporate Procurement" : achats internes de la BAD elle-même (informatique,
#    facilities, télécoms...), tous bureaux confondus dans le monde — y COMPRIS
#    son siège à Abidjan. Vérifié en direct : contenu réellement pertinent pour
#    une PME de conseil IT ("Static Application Security (SAST)...", "Security
#    Service Edge (SSE) Solution", "High Speed Internet Connectivity Solution"),
#    et un avis vu portant explicitement sur la "cité BAD à Abidjan". Pas de
#    filtre pays appliqué ici (contrairement au flux Project Procurement) :
#    un achat pour n'importe quel bureau BAD dans le monde reste ouvert à un
#    prestataire basé à Abidjan (siège), ce n'est pas un marché local restreint.
BAD_CORPORATE_PROCUREMENT_RSS_URL = (
    "https://www.afdb.org/en/about-us/corporate-procurement/procurement-notices/current-solicitations.xml"
)
# Les deux flux RSS ne donnent aucune date limite exploitable (le champ
# <description> ne fait que répéter le titre) — seule la page détail de
# chaque avis l'expose (`field-name-field-procurement-end-date`, avec un
# attribut `content` ISO 8601 directement exploitable). Enrichissement en
# aval, uniquement sur les avis candidats retenus après filtrage (même
# logique que PMMP/ONDA/BCEAO).

# ---------------------------------------------------------------------------
# Sources officielles — Maroc
# ---------------------------------------------------------------------------
# Portail Marocain des Marchés Publics (PMMP) — même moteur "profil
# acheteur" que PLACE/Maximilien (France) : PRADO postback, mêmes conventions
# d'identifiants ctl0_CONTENU_PAGE_.... Recherche multicritères accessible
# sans compte ; nécessite un User-Agent de navigateur réaliste (un WAF bloque
# les requêtes sans en-têtes de navigateur, cf. README).
MA_PMMP_BASE_URL = "https://www.marchespublics.gov.ma"

# domaineActivite=3.19 = "Services de technologies de l'information et
# télécommunications" — catégorie officielle du référentiel PMMP, équivalent
# du CPV 72 pour ce portail (trouvée en énumérant les liens de catégorie de
# la page d'accueil publique).
#
# IMPORTANT — testé en direct : combiner "&EnCours&domaineActivite=3.19" dans
# la même URL casse le moteur de recherche côté serveur (page de résultats
# vide, aucune erreur explicite) alors que chaque filtre fonctionne
# séparément (EnCours seul -> 3551 résultats ; domaineActivite=3.19 seul ->
# 1098 résultats). On interroge donc UNIQUEMENT domaineActivite=3.19 (toutes
# dates, ouvertes et closes) et on laisse filter_classify.is_deadline_too_soon
# écarter les consultations déjà closes, exactement comme pour les autres
# sources — plutôt que de dépendre d'une combinaison d'URL fragile.
MA_PMMP_SEARCH_URL_IT = (
    "https://www.marchespublics.gov.ma/index.php"
    "?page=entreprise.EntrepriseAdvancedSearch&AllCons&domaineActivite=3.19"
)
# Programme prévisionnel (équivalent APProch) — projets d'achat annoncés par
# les acheteurs avant publication formelle de l'avis. Page confirmée
# accessible sans compte ; structure non encore validée en détail (formulaire
# PRADO, cf. README) — utilisée en best-effort par collector_maroc_ppm.py.
MA_PMMP_PPS_URL = "https://www.marchespublics.gov.ma/index.php?page=entreprise.ListePPs"

# ---------------------------------------------------------------------------
# Source complémentaire — ONDA (Office National Des Aéroports, Maroc)
# ---------------------------------------------------------------------------
# Investigation menée le 05/08/2026 pour déterminer si les grands
# établissements publics marocains (ONDA, ONEE, Marsa Maroc, ANP, CDG, ADM)
# apportent une couverture réelle en plus du PMMP déjà scrappé :
# - Marsa Maroc, CDG (SAFAKAT), ADM : portails dédiés avec mur de connexion
#   dès la liste des avis — écartés (pas d'accès public sans compte).
# - ANP : page publique techniquement accessible (testé en Playwright), mais
#   flux composé uniquement d'autorisations d'exploitation portuaire
#   (gardiennage, récupération de détritus, concessions...) — zéro avis IT
#   constaté, hors cible.
# - ONEE : page publique sans compte, mais zéro avis IT sur les catégories
#   "fournitures" et "grands projets/travaux" testées, et recherche par
#   mot-clé "informatique"/"système" infructueuse à chaque fois — flux dominé
#   par du matériel électrique et des travaux de réseau, hors cible.
# - ONDA : gain réel confirmé. Page "Appels d'offres Achats" publique, sans
#   compte, rendue côté serveur (`requests` seul suffit, pas de WAF/JS),
#   robots.txt ne bloque que Bingbot/SemrushBot/AhrefsBot. Contient des avis
#   IT réels et récurrents (ex. formations RedHat/CISCO, plateforme de
#   gestion numérique, laboratoire SMART GRID).
#
# Point important constaté sur une page détail ONDA : le dossier de
# consultation est en réalité hébergé sur le PMMP (lien direct vers
# EntrepriseDetailsConsultation), avec la mention explicite "en cas de
# divergence [...] seules les informations publiées sur le PMMP font foi".
# Vérification faite sur cet avis précis (formation RedHat/CISCO,
# refConsultation=1028954) : sa catégorie PMMP réelle est "Services /
# Services courants / Formation du personnel" — PAS domaineActivite=3.19
# (IT), la seule catégorie interrogée par collector_maroc.py. Un avis IT
# publié par l'ONDA peut donc être invisible du scrape PMMP par simple effet
# de catégorisation côté acheteur, indépendamment de la pagination — la page
# ONDA elle-même liste TOUS ses avis sans filtre de catégorie PMMP, et c'est
# notre propre filtrage par mots-clés (filter_classify) qui rattrape ce que
# la catégorisation PMMP peut rater.
MA_ONDA_LISTING_URL = "https://www.onda.ma/Je-suis-Professionnel/Appels-d'offres/Appels-d'offres-Achats"

# ---------------------------------------------------------------------------
# LLM (réservé — non utilisé par la collecte de base, cf. run_collect.py)
# ---------------------------------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
