"""Configuration centrale du pipeline de veille des appels d'offres IT — CFConsulting.

Toutes les valeurs "métier" (CPV, mots-clés, seuils) vivent ici pour que
filter_classify.py, collector_boamp.py etc. restent des modules sans état
métier codé en dur.
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
DCE_DIR = DATA_DIR / "dce"
LOG_DIR = BASE_DIR / "logs"
EXCEL_PATH = DATA_DIR / "veille_appels_offres.xlsx"

for _d in (DATA_DIR, DCE_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Seuils métier (PME de conseil IT)
# ---------------------------------------------------------------------------
# Montant HT au-dessus duquel un marché sort de la cible PME (section OBJECTIF).
SEUIL_MONTANT_MAX = 100_000

# Un accord-cadre dont le montant/plafond connu dépasse ce seuil est exclu
# (trop gros pour une PME de conseil). Si le montant est inconnu, on garde.
SEUIL_ACCORD_CADRE = 100_000

# Délai minimal (jours) entre aujourd'hui et la date limite de soumission
# pour qu'un avis reste dans l'Excel — en dessous, pas le temps de constituer
# une réponse sérieuse.
DELAI_MIN_SOUMISSION_JOURS = 7

# ---------------------------------------------------------------------------
# CPV ciblés — famille 72 = "Services de TI : conseil, développement de
# logiciels, internet et appui" (cf. simap.ted.europa.eu)
# ---------------------------------------------------------------------------
CPV_PREFIXES_CIBLES = ("72",)

# CPV explicitement HORS cible même si le texte contient des mots IT ambigus.
# 71 = architecture / ingénierie ; 45 = travaux de construction.
CPV_PREFIXES_EXCLUS = ("71", "45")

# ---------------------------------------------------------------------------
# Mots-clés IT — domaine cible (recherche insensible à la casse dans l'objet)
# ---------------------------------------------------------------------------
# Termes FORTS : sans ambiguïté sectorielle, suffisants seuls pour confirmer
# le domaine IT.
MOTS_CLES_IT_FORTS = [
    "power bi", "business intelligence", "décisionnel", "decisionnel",
    "dataviz", "data visualization", "visualisation de données",
    "talend", "etl",
    "développement logiciel", "developpement logiciel",
    "développement applicatif", "developpement applicatif",
    "développement web", "developpement web",
    "développement informatique", "developpement informatique",
    "logiciel", "applicatif", "progiciel",
    "système d'information", "systeme d'information", "système d’information",
    "sirh",
    "site internet", "site web", "application mobile",
    "base de données", "base de donnees",
    "cybersécurité", "cybersecurite",
    "conseil en systèmes d'information",
]

# Termes AMBIGUS : "AMOA"/"maîtrise d'ouvrage" sont des termes génériques
# utilisés dans TOUS les secteurs (BTP, environnement, assurance, culture...),
# pas seulement l'IT. Un match sur ces termes seuls ne suffit PAS à confirmer
# le domaine IT — il faut un terme de contexte IT (MOTS_CLES_CONTEXTE_IT)
# également présent (cf. filter_classify.classify_domain).
MOTS_CLES_AMBIGUS = [
    "amoa", "amo si", "assistance à maîtrise d'ouvrage",
    "assistance a maitrise d'ouvrage", "maîtrise d'ouvrage", "maitrise d'ouvrage",
]

MOTS_CLES_CONTEXTE_IT = [
    "système d'information", "systeme d'information", "système d’information",
    "informatique", "numérique", "numerique", "digital",
    "logiciel", "applicatif", "sirh", "si ",
]

# Liste complète utilisée pour la recherche côté API (recall large — le tri
# précis se fait ensuite dans filter_classify.classify_domain).
MOTS_CLES_IT = MOTS_CLES_IT_FORTS + MOTS_CLES_AMBIGUS

# ---------------------------------------------------------------------------
# Mots d'exclusion — BTP / bâtiment / environnement. Utilisés pour écarter les
# faux positifs quand AMO/AMOA/"maîtrise d'ouvrage" est associé à ces domaines
# ET qu'aucun signal IT fort n'est présent par ailleurs.
# ---------------------------------------------------------------------------
MOTS_EXCLUSION = [
    "bâtiment", "batiment", "voirie", "vrd", "réseaux secs", "reseaux secs",
    "assainissement", "urbanisme", "paysage", "espaces verts",
    "construction", "réhabilitation", "rehabilitation",
    "démolition", "demolition", "travaux", "gros oeuvre", "gros œuvre",
    "génie civil", "genie civil",
    "aménagement urbain", "amenagement urbain",
    # "maîtrise d'oeuvre" (loi MOP) désigne toujours une mission de conception
    # architecturale/technique pour un ouvrage de construction — à l'inverse
    # de "maîtrise d'ouvrage" (rôle transversal ambigu), ce terme n'a aucun
    # sens en informatique.
    "maîtrise d'oeuvre", "maitrise d'oeuvre", "maîtrise d'œuvre",
    "thermique", "chauffage", "voierie",
    "signalisation routière", "signalisation routiere",
    "éclairage public", "eclairage public",
    # Environnement / écologie (également hors cible, cf. objectif métier)
    "écologue", "ecologue", "écologique", "ecologique",
    "mesures compensatoires", "mesure compensatoire",
    "biodiversité", "biodiversite", "milieux naturels",
    # Accessibilité physique de bâtiments (à distinguer de l'accessibilité
    # numérique RGAA, qui reste IT si "numérique"/"web" est mentionné)
    "mise en accessibilité", "mise en accessibilite",
    "accessibilité pmr", "accessibilite pmr",
    "personnes à mobilité réduite", "personnes a mobilite reduite",
    "cité scolaire", "cites scolaires", "cités scolaires",
    # Signalétique / mobilier urbain physique
    "signalétique", "signaletique", "mobilier urbain",
    # Maintenance / infogérance / TMA pure (hors scope PME de conseil —
    # missions récurrentes de run, pas de projet de développement/conseil).
    # Un mélange développement+maintenance reste "IT confirmé" tant qu'un
    # terme IT fort (ex. "développement") est également présent.
    "infogérance", "infogerance", "tierce maintenance applicative",
    "tma", "maintien en condition opérationnelle", "mco",
    "contrat de maintenance", "maintenance corrective", "maintenance évolutive",
    "maintenance corrective et évolutive", "maintenance applicative",
    "maintenance et support", "reprise de la maintenance",
]

# Mots d'exclusion FORTE — dominent TOUJOURS, même en présence d'un mot-clé
# IT fort (ex. "Acquisition de licences Business Intelligence" reste exclu
# malgré "Business Intelligence"). Décrivent la NATURE du marché (achat/
# fourniture) plutôt que son sujet : hors scope pour une PME de conseil qui
# vend des prestations de service, pas des licences/matériel.
# Détection par CO-OCCURRENCE plutôt que par phrase exacte : la formulation
# réelle des avis varie trop ("Acquisition, hébergement et maintenance d'un
# logiciel...", "Acquisition et installation d'une solution logicielle...")
# pour qu'un matching de phrase adjacente soit fiable. Un marché est
# considéré comme un achat/fourniture directe (hors scope) si un verbe
# d'acquisition ET un objet matériel/logiciel apparaissent tous deux dans le
# texte, peu importe leur ordre ou leur proximité.
MOTS_ACQUISITION = [
    "acquisition", "acquérir", "acquerir", "achat", "acheter",
    "renouvellement de licence", "renouvellement de licences",
]

MOTS_OBJET_MATERIEL = [
    "logiciel", "licence", "licences", "matériel", "materiel",
    "équipement", "equipement", "progiciel", "solution logicielle",
]

# "Fourniture(s)" est traité comme un verbe d'acquisition à part, car très
# fréquent dans les intitulés d'achat direct ("Fourniture d'un logiciel...").
# EXCEPTION : "fourniture de prestations/services" est une tournure
# administrative courante signifiant "prestation de service", PAS un achat
# de bien — ne doit jamais déclencher l'exclusion à elle seule.
MOTS_FOURNITURE = ["fourniture", "fournitures"]
FOURNITURE_SERVICE_EXCEPTIONS = [
    "fourniture de prestations", "fournitures de prestations",
    "fourniture des prestations", "fourniture de service", "fourniture de services",
]

# Phrase figée résiduelle : signale un marché de fourniture pure même sans
# objet matériel nommé explicitement à proximité.
MOTS_EXCLUSION_FORTE = [
    "fourniture, installation et maintenance",
]

# ---------------------------------------------------------------------------
# Fournisseur LLM pour la synthèse (section 8 du cahier des charges)
# ---------------------------------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")  # "gemini" | "anthropic" | "local"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Modèles gratuits (free tier Google AI Studio) : Flash / Flash-Lite uniquement.
# Vérifier l'id exact sur https://ai.google.dev/gemini-api/docs/models avant usage prod.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MAX_REQUESTS_PER_MINUTE = int(os.getenv("GEMINI_MAX_REQUESTS_PER_MINUTE", "10"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Modèle rapide/économique adapté à l'extraction structurée PDF -> JSON.
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")

# ---------------------------------------------------------------------------
# Réseau — respect des CGU des plateformes / robots.txt (section SECURITE)
# ---------------------------------------------------------------------------
USER_AGENT = "CFConsulting-VeilleAO/1.0 (usage raisonnable ; contact: rgueriatou@gmail.com)"
HTTP_TIMEOUT = 30
REQUEST_DELAY_SECONDS = 1.5  # délai minimal entre requêtes vers un même hôte

# ---------------------------------------------------------------------------
# APIs sources (section SOURCES OFFICIELLES — n'en inventer aucune autre)
# ---------------------------------------------------------------------------
BOAMP_API_URL = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"
APPROCH_API_URL = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/projets-dachats-publics/records"

BOAMP_PAGE_SIZE = 100
APPROCH_PAGE_SIZE = 100
