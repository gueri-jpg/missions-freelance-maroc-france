# -*- coding: utf-8 -*-
"""
Couche de CLASSIFICATION (post-traitement pur, sans réseau).

Principe directeur : LE TEXTE PRIME SUR LE LABEL LinkedIn.
Le champ « Temps plein / Contrat » n'est pas fiable (BROME étiquette
« Temps plein » des annonces qui disent « Mission Freelance »).

Point d'entrée principal :
    classifier(annonce: dict, today: str|None) -> dict
        classe UNE annonce (type réel, banque, cœur métier, domaine, âge,
        fenêtre provisoire, question B2B...).

    classify_all(annonces: list, today: str|None) -> list
        applique classifier() à chaque annonce PUIS calcule les signaux
        croisés (multi_esn, vivier) et le VERDICT final.

Aucune dépendance réseau : testable seul.  Voir test_classifier.py.
"""

import re
import unicodedata
import datetime as dt

# --------------------------------------------------------------------- LEXIQUES

# §3 — secteur bancaire : présence dans le texte => banque = OUI
BANK_TEXT_KW = [
    "bancaire", "banque", "core banking", "monétique", "monetique",
    "moyens de paiement", "sepa", "swift", "corporate banking",
    "digital banking", "risque de crédit",
    "conformité bancaire", "amplitude", "trade finance", "e-banking",
    "cash management",
]
# Mots bancaires COURTS : a matcher en MOT ENTIER, JAMAIS en sous-chaine.
# has_any() compare en sous-chaine ; en liste nue ces mots attrapaient
# n'importe quoi (mesure du 2026-07-17 : 112 faux "banque = OUI") :
#   "cib"    -> "cible", "cibles", "ne ciblent pas"   (omnipresent en IT FR !)
#   "bale"   -> "globale", "verbale"
#   "alm"    -> "palmares", "Almatek" (nom de cabinet)
#   "credit" -> "accreditation"
# On garde les suffixes utiles : credits, crédit-bail, Bale II/III.
BANK_WORD_RE = re.compile(
    r"\b(cib|alm|b[âa]le\s*(?:ii|iii|2|3)?|cr[ée]dits?|cr[ée]dit-bail"
    r"|t24|sab|opcvm)\b", re.I)
# Mots bancaires GENERIQUES (par opposition aux specifiques ci-dessus) : ce sont
# les seuls qu'une plaquette d'ESN peut citer sans que la mission soit bancaire.
BANK_GENERIC_KW = ["banque", "banques", "bancaire", "bancaires", "banking"]
_BANQUE_RE = re.compile(r"banques?|bancaires?|banking", re.I)
# Secteurs NON bancaires : servent a reperer une ENUMERATION de plaquette.
AUTRES_SECTEURS_KW = [
    "energie", "transport", "mobilite", "luxe", "distribution", "sante",
    "industrie", "telecom", "aeronautique", "retail", "secteur public",
    "defense", "automobile", "media", "tourisme", "agroalimentaire",
    "utilities", "pharma", "assurance", "mutuelle", "immobilier",
    "logistique", "e-commerce", "spatial", "life sciences", "btp",
]


def _banque_seulement_enumeration(blob):
    """La plaquette d'une ESN enumere ses secteurs ("banques et services
    financiers, energie, transport, luxe, sante") : ce n'est PAS la preuve que
    la MISSION est bancaire.

    Cas reel (2026-07-17) : "Chef de projet GMAO Senior" chez Talan (maintenance
    industrielle) etait classe banque par cette seule phrase ; 72 annonces
    concernees, quasiment toutes des annonces Data/BI generiques d'ESN.

    On raisonne par PHRASE, pas par distance : une enumeration de secteurs vit
    dans UNE phrase ("... dans les secteurs de la banque, de l'assurance, de
    l'industrie et du retail."), alors qu'une vraie mention vit dans la sienne
    ("Pour cette mission, notre client bancaire souhaite..."). Une fenetre de
    N caracteres debordait sur la phrase voisine et perdait les vraies missions.

    Vrai seulement si TOUTES les mentions bancaires sont dans une phrase
    enumerative : une seule mention hors liste suffit a valider le signal, donc
    une vraie mission en banque publiee par une ESN a plaquette n'est jamais
    perdue.
    """
    if not _BANQUE_RE.search(blob):
        return False
    for phrase in re.split(r"[.!?;\n\r]+", blob):
        if not _BANQUE_RE.search(phrase):
            continue
        p = strip_accents(phrase).lower()
        # Seuil releve de 2 a 3 le 2026-07-21 : une VRAIE plaquette d'ESN liste
        # BEAUCOUP de secteurs ("banque, energie, transport, luxe, sante..." = 5+).
        # A 2, une offre BANCASSURANCE (pole valide) tombait a tort : elle contient
        # naturellement "assurance" + "distribution" (de produits) = 2 secteurs.
        # A 3, les plaquettes reelles (Talan 6, HN Services 4...) restent prises.
        if sum(1 for s in AUTRES_SECTEURS_KW if s in p) < 3:
            return False        # mention bancaire hors enumeration => vrai signal
    return True
# §3 — cabinets qui placent quasi exclusivement en banque => banque = PROBABLE
BANK_PROBABLE_CABINETS = ["brome", "gec", "global experts", "adaptive",
                          "it-adaptive", "fininfo"]
# Termes bancaires FORTS (lèvent le doute même en contexte 'finance' ambigu)
STRONG_BANK_KW = ["banque", "bancaire", "banking", "monétique", "monetique",
                  "swift", " alm ", "core banking", "moyens de paiement",
                  "corporate banking", "digital banking", "e-banking"]
# Contextes 'finance' NON bancaires (crédit d'impôt, financement innovation...)
BANK_NEG_KW = ["crédit d'impôt", "credit d'impot", "crédit impôt",
               "credit impot", "financement de l'innovation", "innovation f/h",
               "crédit impot recherche", "subvention", " cir "]
# Secteurs client clairement NON bancaires (via le champ "Secteur d'activité"
# des fiches) : dégrade un cabinet "banque probable" à NON.
NON_BANK_SECTOR_KW = [
    "commerce de détail", "commerce de detail", "commerce de gros",
    "grande distribution", "retail", "télécommunication", "telecommunication",
    "télécom", "telecom", "industrie automobile", "transport", "logistique",
    "e-commerce", "e-santé", "santé et", "sante et", "immobilier", "tourisme",
    "agroalimentaire", "énergie", "energie",
    # SECTEUR SANTE / HOSPITALIER (2026-07-21) : un cabinet "probablement banque"
    # (BROME) place aussi dans la sante -> "PMO Senior Projets Sante" (SIH
    # hospitalier) passait en PROBABLE. On vise le SECTEUR sante, PAS "assurance
    # santé"/"prévoyance" (= bancassurance, pole valide). Mesure : 1 seule offre
    # touchee, 0 bancassurance impactee.
    "secteur de la santé", "secteur de la sante", "secteur santé", "secteur sante",
    "domaine de la santé", "domaine de la sante", "hospitalier", "hospitalière",
    "hospitaliere", "établissement de santé", "etablissement de sante",
    "santé publique", "sante publique", " sih", "sih)",
]

# §4 — cœur de métier CFConsulting
COEUR_METIER_KW = [
    "data", " bi ", "business intelligence", "power bi", "talend", " etl ",
    "data gouvernance", "data governance", "data quality", "data analyst",
    "data architect", "data engineer", "reporting", "tableau de bord",
    "décisionnel", "decisionnel", "migration de données", "migration de donnees",
    "data steward", "datawarehouse", "data warehouse", "dataviz",
]
# §4 — domaines acceptés (perimetre valide par l'utilisatrice 2026-07-17) :
# PMO / pilotage / gouvernance + AMOA / MOA / BA + Product Owner / Scrum.
# Le DEVELOPPEMENT est volontairement EXCLU (voir EXCLUS_TECH_KW).
DOMAINE_OK_KW = [
    "amoa", "moa", "pmo", "chef de projet", "cheffe de projet",
    "business analyst", "business analyste", "product owner", "proxy po",
    "maîtrise d'ouvrage", "maitrise d'ouvrage", "scrum", "pilotage",
    "gouvernance", "conduite du changement", "chef de programme",
    "directeur de projet", "coordinateur projet",
]

# §4a — exclusions DURES : jamais pertinent, meme si data/BI apparait.
#   - paiement / monetique (regle utilisatrice : "les offres de paiement ne conviennent pas")
#   - urbanisation / chef de projet SI (trop technique/architecture)
#   - cyber, reseau, infra, prod, support
EXCLUS_HARD_KW = [
    # PAIEMENT / MONETIQUE : NE SONT PLUS EXCLUS (2026-07-20). Les tuteurs les
    # ont valides comme poles metier ("Paiements & Monetique") -> une mission
    # AMOA/PMO/BA/PO sur la monetique est desormais DANS le perimetre. Seuls les
    # ROLES hors perimetre (dev, QA, production, support, back-office metier)
    # restent exclus par les autres regles ci-dessous, monetique ou pas.
    # (Bloc "paiement/paiements/payment/monétique/sepa/encaissement/acquiring/
    # moyens de paiement/carte bancaire/tpe/fraude monétique" retire.)
    # urbanisation / projet SI purement technique
    "urbanisation", "projet si", "si fonctionnel", "architecte si",
    # cyber / reseau / infra / prod / support
    # "cyber" seul ajoute le 2026-07-21 : "PMO cyber senior" (LeHibou, secteur
    # banque) passait car seul "cybersécurité" etait exclu. La cyber n'est pas
    # dans les 11 poles. Aucun mot bancaire ne contient "cyber" -> sans risque.
    "cyber", "cybersécurité", "cybersecurite", "cyber sécurité", "sécurité réseau",
    "réseaux", "reseaux", "réseau", "reseau", "infrastructure", "infra ",
    "support n1", "support niveau 1", "support applicatif", "helpdesk",
    "hotline", "administrateur système", "administrateur réseau",
    "ingénieur de production", "ingenieur de production", "ingénieur de prod",
    "devops", "infogérance", "infogerance", "run applicatif", "supervision",
    "openshift",
    # QA / test / recette (regle utilisatrice 2026-07-17)
    "test lead", "test manager", "testeur", "testeuse", " qa ", "qa automation",
    "recette",
    "homologateur", "homologation", "istqb", "alm octane", "hp alm",
    "quality assurance", "tests automatis", "qualification fonctionnelle",
    # FINANCE METIER *NON IT* (roles metier, pas pilotage) : le perimetre reste
    # le pilotage/AMOA/data IT bancaire. On garde ces ROLES exclus, mais PAS les
    # domaines valides par les tuteurs (ALM, Risques...) -> "liquidity",
    # "liquidité bancaire", "gestionnaire de bilan" RETIRES le 2026-07-20 (pole
    # "ALM"). Restent exclus les vrais roles non-IT :
    "contrôleur de gestion", "controleur de gestion", "comptable",
    "comptabilité", "comptabilite", "actuaire", "actuariat",
    "consolidation", "quantitatif", "analyste financier", "risk manager",
    # identites / formation (NB : " formation " avec espaces — sinon on
    # attraperait "TRANSformation", omnipresent dans les missions bancaires)
    " iam", "ciam", "keycloak", "habilitation", "formateur", " formation ",
    # METIERS NON-IT (2026-07-17) : une banque recrute aussi hors IT. Un
    # "chef de projet" n'est dans le perimetre que si le projet est IT
    # (fuite reelle detectee : "CHEF DE PROJETS IMMOBILIER", Banque de France).
    # NB : PAS de "immobilier" nu — "BA Crédit Immobilier" est une VRAIE
    # mission IT bancaire (credit habitat). On ne vise que le metier batiment.
    "projet immobilier", "projets immobilier", "responsable immobilier",
    "gestion immobilière", "gestion immobiliere", "patrimoine immobilier",
    "conducteur de travaux", "projet travaux", "chef de projet bâtiment",
    "chef de projet batiment", "second oeuvre", "maîtrise d'oeuvre bâtiment",
    # CASH MANAGEMENT / TRESORERIE : NE SONT PLUS EXCLUS (2026-07-20). L'exclusion
    # du 19/07 est ANNULEE : les tuteurs valident l'ALM (qui recouvre la
    # tresorerie) et la migration TMS fait partie des competences idéales
    # ("Piloter des projets de migration de solutions Treasury Management
    # System"). Une mission AMOA/PMO/BA sur la tresorerie/TMS est donc DANS le
    # perimetre. (Bloc "cash management/tresorerie/treasury/iso 20022/kyriba/
    # sage xrt/gtreasury/cash pooling" retire.)
    # stage / alternance : jamais de la regie
    " stage", "stagiaire", "alternance", "alternant", "apprentissage",
    "chef de projet marketing", "chef de projet communication",
    "chef de projet évènementiel", "chef de projet evenementiel",
    "chef de projet rse", "chef de projet juridique",
    "chef de projet logistique", "chargé de communication",
    # --- Lot 2026-07-20 (offres rejetees explicitement par l'utilisatrice) ---
    # Outil tres specifique. NB : "dataiku" contient "data" -> sans cette ligne,
    # le stade 2 (COEUR_METIER "data") le prenait pour du Data/BI.
    "dataiku",
    # Relation client / onboarding : "c'est plus relation client que chef de
    # projet" (STHREE "Onboarding Customer" -> coordination client via Salesforce)
    "onboarding customer", "customer onboarding", "onboarding client",
    "relation client", "chargé de clientèle", "charge de clientele",
    # Qualite (manager qualite, manuel qualite) : distinct de "data quality"
    # (= coeur) ; on vise la fonction qualite/gouvernance interne.
    "quality manager", "manager qualité", "manager qualite",
    "responsable qualité", "responsable qualite", "manuel qualité",
    "manuel qualite", "quality assurance manager",
    # Poste / support / run Microsoft 365 (infra, pas pilotage)
    "m365", "microsoft 365", "office 365", "o365",
    "support l2", "support l3", "support n2", "support n3", "run & support",
    # Inspection / audit bancaire (metier, pas IT) : CIC "Inspecteur/Inspectrice"
    "inspecteur", "inspectrice", "auditeur interne", "auditrice interne",
    # Reporting REGLEMENTAIRE / prudentiel (solvabilite, RWA, COREP/FINREP) :
    # NE SONT PLUS EXCLUS (2026-07-20). Les tuteurs valident "Risques" et "ALM"
    # comme poles, et "tableaux de bord BI / indicateurs de suivi" comme
    # competences -> une mission AMOA/PMO/BA/Data sur le reporting prudentiel est
    # dans le perimetre. (Bloc "solvabilité/rwa/reporting prudentiel/corep/finrep"
    # retire.) NB : les instruments FISCAUX extraterritoriaux (FATCA/AEOI/DAC 6/
    # 871m) restent exclus via FINANCE_REG_TEXTE_KW (fiscalite specifique, hors
    # des 11 poles, rejetee nommement par l'utilisatrice le 20/07).
]

# Termes de paiement recherches dans le TEXTE (cf. detect_domaine, etage 1bis).
# Volontairement SANS le mot "paiement" nu, bien trop frequent : une annonce
# bancaire cite ses metiers ("credit, epargne, moyens de paiement") sans etre
# une mission de paiement pour autant.
PAIEMENT_TEXTE_KW = [
    "monétique", "monetique", "moyens de paiement", "encaissement",
    "acquiring", "carte bancaire", "cartes bancaires", "chèque", "cheque",
    "terminal de paiement", "tpe",
]
# Locutions "produit paiement" : le paiement EST le sujet/livrable de la mission
# (le produit qu'on deploie), pas une competence listee -> UN SEUL terme exclut.
# Distinction verifiee le 2026-07-17 :
#   CELAD "deploiement de SOLUTIONS DE PAIEMENT critiques (emission, acquisition)"
#   VISIAN "SERVICES DE PAIEMENT et monetique, domaine Paiements"     -> ecartes
#   STHREE "Connaissance du domaine des paiements / monetique (un plus)" -> garde
#   Foster "Perimetre : Credit, Compta, Monetique, Paiement, Risques"    -> garde
# 'monétique'/'domaine des paiements' restent au palier FAIBLE (>=2) car souvent
# cites comme simple competence ("un plus") sans etre le sujet de la mission.
# CERTIFICATIONS SI : une annonce qui empile les certifications ne decrit pas une
# MISSION mais un profil "expert SI certifiant" -> hors perimetre (regle
# utilisatrice 2026-07-19 : "les competences et certifications demandees sont
# trop specifiques, orientees SI, ca ne convient pas").
# Cas reel : BROME "Expert gouvernance SI et PMO" listait CGEIT, COBIT, TOGAF,
# BPMN2, PMP, PRINCE2, CMMI, Lean Six Sigma, APMG Lean IT, ITIL V4, ITIL OSA,
# SCRUM, ISO 27001, CISA, COMPTIA Cloud+, CDCP... et AUCUNE mission decrite.
# Seuil a 3 : une annonce normale cite 1-2 certifications sans probleme
# (mesure 2026-07-19 : 1 seule offre touchee sur tout le cache, la bonne).
# Dispositifs FISCAUX / REGLEMENTAIRES extraterritoriaux : instruments non
# ambigus (aucune occurrence incidente plausible) -> cherches dans le TEXTE.
# Cas reel 2026-07-20 : "Senior Regulatory Change Project Manager" (titre
# generique de PM) dont la mission portait sur FATCA/AEOI, DAC 6, Section
# 871(m) -> finance metier fiscal, hors perimetre, "differente de l'offre
# ideale". FINAX "Conformite Reglementaire" (PMO) ne contient AUCUN de ces
# termes (verifie) -> non impacte.
FINANCE_REG_TEXTE_KW = [
    "fatca", "aeoi", "dac 6", "dac6", "dac6/", "871(m)", "section 871",
    "crs/fatca", "fatca/crs", "qi/fatca", "impôt à la source", "impot a la source",
    "retenue à la source", "withholding tax",
]

# GEOGRAPHIE : le perimetre est FRANCE + MAROC. Une mission clairement situee
# ailleurs est hors scope. Cas reel 2026-07-20 : "Project finance SME - drawdown
# management (Sao Paulo, Brazil)" -> "au Bresil, hors scope". On cherche ces
# marqueurs dans le TITRE et la VILLE (pas le texte : "deploiement international"
# ou "client anglophone" ne doit PAS exclure une mission basee en France).
GEO_HORS_SCOPE_KW = [
    "brazil", "bresil", "sao paulo", "dubai", "abu dhabi", "qatar", "doha",
    "london", "londres", "geneve", "geneva", "zurich", "luxembourg",
    "bruxelles", "brussels", "belgique", "belgium", "montreal", "new york",
    "singapore", "singapour", "hong kong", "allemagne", "germany", "berlin",
    "munich", "madrid", "barcelone", "barcelona", "espagne", "spain", "milan",
    "milano", "italie", "italy", "amsterdam", "pays-bas", "riyadh", "riyad",
    "abidjan", "dakar", "tunis", "tunisie", "senegal", "cote d'ivoire",
]


def hors_geographie(poste, ville):
    """True si la mission est clairement hors France+Maroc (titre ou ville)."""
    blob = strip_accents(f"{poste} {ville}").lower()
    return any(k in blob for k in GEO_HORS_SCOPE_KW)


CERTIF_SI_KW = [
    "cgeit", "cobit", "togaf", "bpmn", "prince2", "cmmi", "six sigma",
    "lean it", "itil", "iso 27001", "iso/iec 27001", "iso/ifc 27001",
    "cisa", "comptia", "cdcp", "dcfc", "cissp", " pmp ", "cobit 5",
]
SEUIL_CERTIF = 3

PAIEMENT_FORT_KW = [
    "solution de paiement", "solutions de paiement",
    "service de paiement", "services de paiement",
    "émission et acquisition", "emission et acquisition",
    "émission, acquisition", "emission, acquisition", "acquiring",
]

# §4b — exclusions TECHNIQUES : dev / stacks / outils metier specifiques.
# Ne s'appliquent PAS si le titre porte un mot Data/BI (= coeur metier garde).
EXCLUS_TECH_KW = [
    "développeur", "developpeur", "développeuse", "dévelopement",
    "développement", "developpement", "lead developer", "tech lead",
    "concepteur-développeur", "intégrateur", "integrateur", "moe", "amoe",
    "architecte technique", "architecte solution", "architecte d'intégration",
    "java", "j2ee", "cobol", "pacbase", "murex", "calypso", "sophis",
    "summit", "loaniq", "loan iq", "temenos", " t24 ", "amplitude", " sab ",
    "kafka", "angular", "react", "spring", "springboot", "python", "c++",
    ".net", "c#", "fullstack", "full stack", "backend", "back-end",
    "frontend", "front-end", "mainframe", "ios", "android", "drupal", "odoo",
    # ERP / progiciels tres specifiques (2026-07-20) : profil expert-outil, pas
    # pilotage. "Technico-Fonctionnel Peoplesoft" = ERP compta/conso + support.
    "peoplesoft", "sap fi", "sap mm", "oracle ebs", "sage x3", "cegid",
    "technico-fonctionnel", "technico fonctionnel",
]

# §2 — signaux RÉGIE FORTS : explicites, ils l'emportent même si l'employeur
#       est un client final (une banque ne dit pas 'pour le compte de notre client').
STRONG_REGIE_KW = [
    "mission freelance", "opportunité freelance", "opportunite freelance",
    "offre de mission", "tjm", "taux journalier", "en régie", "en regie",
    " régie ", " regie ", "pour le compte de notre client",
    "pour le compte de son client", "au sein de notre client",
    "chez notre client", "chez le client", "mois renouvelable",
    "mois renouvelables", "portage", "prestation externe", "consultant externe",
    # NB : SINGULIER seulement. "aupres de NOS CLIENTS" (pluriel) a ete RETIRE
    # le 2026-07-17 : c'est la description generique du metier d'une ESN dans
    # une annonce CDI ("nous accompagnons nos clients grands comptes"), pas une
    # mission. Mesure : 16 annonces l'employaient, dans 12 c'etait le SEUL
    # signal de regie -> Aubay x3, Deloitte, EY, Forvis Mazars, TNP, ASI,
    # Synanto, STATERA... 100% des recrutements CDI de grosses ESN.
    # Le SINGULIER ("aupres de notre client") reste un vrai signal : il designe
    # une mission chez UN client identifie.
    "auprès de notre client", "aupres de notre client", "auprès d'un client",
    "aupres d'un client", "auprès de son client",
    # assistance technique / jargon régie grand compte
    "assistance technique", "facturation au temps passé",
    "facturation au temps passe", "budget journalier", "au temps passé",
    "au temps passe",
]
# §2 — signaux RÉGIE FAIBLES : indices, mais insuffisants pour requalifier
#       l'annonce d'un client final (banque) en régie.
WEAK_REGIE_KW = [
    "freelance", "profil freelance", "longue durée", "longue duree",
    "démarrage immédiat", "demarrage immediat", "démarrage asap",
    "demarrage asap", "au sein de la banque",
    # "immersion" RETIRE le 2026-07-17 : verifie sur ses 7 emplois reels, il ne
    # designe JAMAIS une regie mais l'accueil en CDI ("immersion totale au sein
    # de nos equipes", "cursus d'integration comprenant des immersions agence",
    # "programme Immersion, une commande photographique" chez Hermes). C'est du
    # vocabulaire d'onboarding, l'inverse d'un signal de regie -- et il
    # suffisait a lui seul a sauver Aubay du filet anti-recruteurs-CDI.
    "intégration dans l'équipe", "integration dans l'equipe",
    "renfort d'équipe", "renfort d'equipe", "mission longue",
]
REF_RE = re.compile(r"\bref[\s:_\-]*\d{2,}\b", re.I)

# Vraie DECLARATION DE CONTRAT stage / alternance / CDD dans le TEXTE (pas un
# usage incident du mot). Le mot "stage"/"apprentissage"/"alternance" seul est
# trop frequent en contexte non-contractuel (2026-07-21) : "apprentissage
# continu" (culture d'entreprise), "premiere experience (stage ou alternance)"
# (niveau du candidat), "encadrer un stagiaire" (qui on manage). On ne vise
# donc que les formulations ou le CONTRAT lui-meme est un stage/alternance/CDD.
STAGE_ALT_CDD_RE = re.compile(
    r"type de (?:recrutement|contrat|poste)\s*:\s*(?:stage|stagiaire|alternance"
    r"|apprentissage|cdd)"
    r"|contrat de stage|convention de stage|stage conventionn|gratification de stage"
    r"|offre de stage|poste de stagiaire|stage de fin d|recherchons? un\(?e?\)? stagiaire"
    r"|recrutons? un\(?e?\)? stagiaire"
    r"|contrat d.?(?:alternance|apprentissage)|poste en alternance|offre d.?alternance"
    r"|recherchons? un\(?e?\)? alternant|type de recrutement\s*:\s*contrat",
    re.I)

# Accessibilité B2B (société de conseil / TJM) : la mission t'est ouverte
B2B_ACCESS_KW = [
    "freelance", "tjm", "taux journalier", "société de conseil",
    "societe de conseil", "b2b", "b to b",
    "auto-entrepreneur", "auto entrepreneur",
    # "independant" NU RETIRE le 2026-07-20 : il attrapait l'AUTO-DESCRIPTION
    # d'une entreprise ("societe de gestion INDEPENDANTE", "cabinet
    # INDEPENDANT", et le nom de cabinet "Mon Consultant Independant") et
    # rouvrait a tort des annonces CDI. Cas reels : Moneta Asset Management
    # ("Contrat : CDI" + "societe de gestion independante") et MPG Partners
    # ("cabinet de conseil" + mutuelle) redevenaient accessibles. On ne garde
    # que les formes ou "independant" designe le CANDIDAT/le contrat.
    "consultant indépendant", "consultant independant",
    "travailleur indépendant", "travailleur independant",
    "statut indépendant", "statut independant", "en indépendant",
    "en independant", "profil indépendant", "profil independant",
    "portage", "sous-traitance", "sous traitance", "profil freelance",
    # NB : " esn " a ete RETIRE — c'est du vocabulaire metier, pas une preuve
    # d'ouverture B2B. Il repechait des annonces CDI (ex. Adria "· CDI" qui
    # mentionnait "ESN" dans son texte de presentation).
    # NB : "prestataire"/"prestation" RETIRES le 2026-07-17 : ils designent le
    # plus souvent un TIERS ("le prestataire qui developpe les programmes") ou
    # une direction interne ("direction des prestations"), PAS le mode
    # d'engagement offert. Mesure : 59 annonces ne tenaient QUE par eux, quasi
    # toutes des banques en CDI (BPCE x5, Banque de France x4, Credit Mutuel,
    # BRED, CA-CIB, Hermes). Ce faux signal cassait la regle CDI ET le filet
    # anti-recruteurs (cas reel : "Chef de Projet IT Bancaire" chez OPEN,
    # marque "Poste en CDI" + PEE/RTT/mutuelle, sauve par "prestataire").
]
# B2B *FORT* : des conditions reellement OFFERTES (freelance, TJM, portage...),
# par opposition a "societe de conseil" qui n'est qu'une AUTO-DESCRIPTION —
# dire ce qu'on EST ne dit pas ce qu'on PROPOSE. Seul le B2B fort peut annuler
# une preuve EXPLICITE de salariat.
# Cas reel 2026-07-17 : "Product Owner X/F/H" (HOUSE OF ABY) affiche "salaire
# entre 35 000 EUR et 45 000 EUR brut par an" = CDI, mais restait 'a confirmer'
# parce que sa plaquette dit "societe de conseil". A l'inverse Tilencia
# n'affiche AUCUN salaire : faute de preuve de salariat la regle ne s'applique
# pas et il reste 'a confirmer', ce qui est le bon traitement.
B2B_FORT_KW = [k for k in B2B_ACCESS_KW
               if k not in ("société de conseil", "societe de conseil")]
# Salariat SEUL (CDI de mission) : régie fermée à une société de conseil
SALARIAT_ONLY_KW = [
    " cdi ", "salarié", "salariee", "salariée", "salaire", "package salarial",
    # CDD = salariat aussi (regle utilisatrice 2026-07-20, confirmee par les
    # tuteurs). Comme le CDI, ecarte SEULEMENT s'il n'y a AUCUNE ouverture
    # freelance/B2B (une annonce "CDD ou freelance" reste accessible). La regle
    # detect_type gere ce cas : has_salariat and not b2b_fort -> recrutement.
    " cdd ", "cdd/", "/cdd", " cdd,", " cdd.", "cdd ou cdi", "cdi ou cdd",
    "contrat à durée déterminée", "contrat a duree determinee",
    "durée déterminée", "duree determinee", "en cdd", "cdd de",
    "avantages sociaux", "mutuelle", "13ème mois", "13e mois",
    "treizième mois", "treizieme mois", "contrat de travail",
    "période d'essai", "periode d'essai", "convention collective",
    "cdi de mission", "titularisation",
    # Declarations CDI explicites + avantages salaries typiques du CDI, lus dans
    # le corps de l'annonce (2026-07-17, cas OPEN "Chef de Projet IT Bancaire"
    # qui affichait "Poste en CDI" + "PEE, Tickets Restaurant, RTT, prime d'ete,
    # prime velo, mutuelle"). Un freelance/regie ne propose JAMAIS ces avantages.
    "poste en cdi", "en cdi à pourvoir", "en cdi a pourvoir", "cdi à pourvoir",
    "cdi a pourvoir", "recrutement en cdi", "recrutons en cdi", "poste à pourvoir en cdi",
    "tickets restaurant", "ticket restaurant", "titres restaurant",
    "plan d'épargne entreprise", "plan d'epargne entreprise", " pee ",
    " rtt ", "prime d'été", "prime d'ete", "prime de vacances", "prime vélo",
    "prime velo", "comité d'entreprise", "comite d'entreprise",
]

# §2 — employeurs CLIENT FINAL (recrutent pour eux-mêmes => CDI)
CLIENT_FINAL_EMPLOYERS = [
    "cih", "société générale", "societe generale", "attijariwafa",
    "banque centrale populaire", "bcp", "crédit du maroc", "credit du maroc",
    "cfg bank", "saham bank", "wafasalaf", "bank of africa", "bmce", "bmci",
    "crédit agricole", "credit agricole", "al barid", "arab bank",
    "cdg capital", "rma", "royale marocaine", "labelvie", "label vie",
    "mobilize", "yassir", "cnexia", "payment center for africa",
    " pca", "umnia", "bti bank", "mobilize financial",
    # --- Banques / assureurs FRANCE (recrutent pour eux-memes = CDI interne) ---
    "crédit mutuel", "credit mutuel", "arkéa", "arkea", "banque populaire",
    "caisse d'épargne", "caisse d'epargne", "bnp paribas", "natixis", "bpce",
    "la banque postale", " lcl ", "boursorama", "hsbc", "milleis", "oney",
    " cic ", "cic lyonnaise", "crédit industriel", "credit industriel",
    "cetelem", "cofidis", "franfinance", "younited", "qonto", "revolut",
    "axa", "generali", "allianz", "cnp assurances", "groupama", "maif",
    "macif", "matmut", "swiss life", "malakoff", "ag2r", "harmonie mutuelle",
]
# Grosses ESN qui recrutent pour LEUR PROPRE effectif (CDI) : jamais accessibles
# en B2B a une societe de conseil (regle utilisatrice, 2026-07-17). On les traite
# comme des clients finaux => ecartees, SAUF signal freelance/TJM explicite.
# Grosses ESN qui recrutent pour LEUR effectif : jamais accessibles en B2B.
# Aubay ajoutee le 2026-07-17 (constat utilisatrice verifie : son site carriere
# n'a que des rubriques "Recrutement/Commerce" et "Stages & Alternances", aucune
# rubrique freelance/mission ; son annonce "Chef de projet IT Assurance" parle
# de CSE et participation = CDI). ESN cotee, ~7000 salaries.
ESN_CDI_ONLY = ["onepoint", "one point", "viseo", "astek", "aubay"]

# ENTITES ECARTEES PAR DECISION DE L'UTILISATRICE (liste noire simple, distincte
# des ESN ci-dessus : ici le motif est commercial/relationnel, pas technique).
# Ajouter une entite ici suffit a faire disparaitre TOUTES ses missions, y
# compris les futures. RED TIC ajoute le 2026-07-20 ("enleve toutes les missions
# de RED TIC") : le cabinet republie en continu (5 nouvelles missions rien que
# dans la MAJ du matin), une suppression manuelle serait donc a refaire chaque
# jour.
ENTITES_ECARTEES = ["red tic", "redtic"]

# §2 — texte « carrière » (=> CDI)
CAREER_TEXT_KW = [
    "rejoignez nos équipes", "rejoignez notre équipe", "rejoindre nos équipes",
    "rejoignez-nous", "notre culture", "nos collaborateurs",
    "évolution de carrière", "evolution de carriere", "plan de carrière",
    "avantages sociaux", "package attractif", "esprit d'équipe",
    "nos valeurs", "pourquoi nous rejoindre", "great place to work",
    # variantes EN / culture d'entreprise (Deloitte, Devoteam, Smile...)
    "#team", "team is responsible", "join our team", "notre tribu",
    "digital transformakers", "nos smiliens", "notre vocation",
    "your role in the", "our team", "life at",
]
# §2 — cabinets connus placeurs en banque (=> a_confirmer si pas de vocab régie)
KNOWN_REGIE_CABINETS = [
    "brome", "gec", "global experts", "consort", "astek", "fininfo",
    "statera", "adria", "trusted advisors", "trusted", "capfi",
    "adaptive", "it-adaptive", "novancy", "altcode", "africashore",
]

QUESTION_B2B = ("Cette mission est-elle toujours ouverte, et accessible en "
                "contractualisation B2B (société de conseil, facturation au "
                "TJM) ?")

# Vocabulaire de signature pour le rapprochement multi-ESN (§6)
SIGNATURE_VOCAB = [
    "pmo", "amoa", "amoe", "moa", "moe", "chef de projet", "business analyst",
    "product owner", "data gouvernance", "data governance", "data quality",
    "data analyst", "data architect", "data engineer", "business intelligence",
    "power bi", "core banking", "monetique", "cash management", "alm",
    "trade finance", "cybersecurite", "digital banking", "change management",
    "finance", "credit", "reporting", "migration", "conformite", "risque",
]


# ---------------------------------------------------------------- OUTILS TEXTE
def strip_accents(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def _strip_invisibles(s):
    """Retire les caracteres invisibles (marques directionnelles LRM/RLM,
    liants, controles) qui cassent la detection. Cas reel 2026-07-21 : Banque
    de France ecrivait "Type de recrutement : ‎ Stage" avec un U+200E entre
    les deux -> le marqueur "recrutement : stage" ne matchait pas."""
    return "".join(c for c in (s or "")
                   if unicodedata.category(c) not in ("Cf", "Cc") or c in "\n\t")


def _pad(s):
    # Chemin chaud (appele des dizaines de fois par offre) : on NE nettoie PAS
    # les invisibles ici -> ce serait O(n) a chaque has_any. Le nettoyage est
    # fait UNE fois a l'entree du classifier (cf. classifier()).
    return " " + (s or "").lower() + " "


def has_any(text, kws):
    t = _pad(text)
    return any(k in t for k in kws)


def which(text, kws):
    t = _pad(text)
    return [k for k in kws if k in t]


def normalize_title(title):
    """Titre normalisé pour comparer les annonces entre cabinets."""
    t = strip_accents(title).lower()
    t = re.sub(r"\(.*?\)", " ", t)                 # (H/F), (Sénior)...
    t = re.sub(r"\bh\s*/?\s*f\b", " ", t)
    t = re.sub(r"\b(senior|junior|confirme|confirmee|expert|experte|"
               r"stagiaire|debutant|freelance|mission|offre|de|d|le|la|les|"
               r"un|une|en|pour|the|and)\b", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def title_signature(title):
    """Ensemble des tokens métier présents dans le titre (pour multi-ESN)."""
    t = strip_accents(title).lower()
    return frozenset(v for v in SIGNATURE_VOCAB if v in t)


# ------------------------------------------------------------------- DATES
_REL_RE = re.compile(r"il y a\s+(\d+)\s*(jour|jours|semaine|semaines|"
                     r"mois|an|ans|heure|heures|minute|minutes)", re.I)


def parse_date(annonce, today):
    """Renvoie (date_iso, age_jours, source). Priorité : date ISO scrapée,
    sinon 'il y a X' relatif, sinon (None, None)."""
    td = dt.date.fromisoformat(today)
    iso = (annonce.get("date_pub") or "").strip()[:10]
    if re.match(r"\d{4}-\d{2}-\d{2}$", iso):
        d = dt.date.fromisoformat(iso)
        return iso, (td - d).days, "iso"
    rel = (annonce.get("posted_relative") or "").replace("\xa0", " ")
    m = _REL_RE.search(rel)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        days = {"heure": 0, "heures": 0, "minute": 0, "minutes": 0,
                "jour": 1, "jours": 1, "semaine": 7, "semaines": 7,
                "mois": 30, "an": 365, "ans": 365}[unit] * n
        d = td - dt.timedelta(days=days)
        return d.isoformat(), days, "relatif"
    return None, None, "inconnu"


_CAND_RE = re.compile(r"(\d+)\s*(?:premiers?\s+candidats?|candidats?|applicants?)", re.I)


def parse_applicants(annonce):
    """Nombre de candidats (int) à partir du texte type '107 candidats' ou
    'Faites partie des 25 premiers candidats'. None si absent."""
    if annonce.get("nb_candidats") not in (None, ""):
        try:
            return int(annonce["nb_candidats"])
        except (ValueError, TypeError):
            pass
    txt = (annonce.get("nb_candidats_txt") or "").replace("\xa0", " ")
    m = _CAND_RE.search(txt)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- CLASSIF UNIT
def detect_type(poste, texte, entite, emploi_label):
    """(type, regie_signal). Règles :
    - Le LABEL LinkedIn (CDI/Temps plein) n'exclut JAMAIS ; seul le texte compte.
    - Client final (banque qui recrute pour elle-même) => recrutement, toujours.
    - Mode régie détecté (fort ou faible) MAIS uniquement en salariat (CDI de
      mission, sans mention B2B/freelance) => a_confirmer (accessibilité B2B ?).
    """
    blob = f"{poste} . {texte}"

    # STAGE / ALTERNANCE / CDD declare dans le texte => recrutement, SANS
    # echappatoire (un stage/alternance n'est jamais de la regie, meme si le mot
    # "freelance" traine ailleurs). Cf. STAGE_ALT_CDD_RE : ne matche que les
    # vraies declarations de contrat, pas "apprentissage continu" & co.
    if STAGE_ALT_CDD_RE.search(_strip_invisibles(blob)):
        return "recrutement", False

    strong = has_any(blob, STRONG_REGIE_KW) or bool(REF_RE.search(blob))
    weak = has_any(blob, WEAK_REGIE_KW)
    label_contrat = "contrat" in (emploi_label or "").lower()
    has_b2b = has_any(blob, B2B_ACCESS_KW) or label_contrat
    has_salariat = has_any(blob, SALARIAT_ONLY_KW)
    # Client final = banque/assureur en direct OU grosse ESN qui recrute en CDI
    # pour elle-meme : dans les deux cas, pas de B2B possible sans preuve explicite.
    client_final = (has_any(entite, CLIENT_FINAL_EMPLOYERS)
                    or has_any(entite, ESN_CDI_ONLY))
    career = has_any(texte, CAREER_TEXT_KW)

    # REGLE UTILISATEUR : une annonce qui dit CDI / salaire / mutuelle SANS
    # aucune ouverture freelance-B2B ("CDI ou freelance", TJM, société de
    # conseil...) est du SALARIAT PUR -> inaccessible a CFConsulting -> ecartee.
    # (Les annonces disent le plus souvent "CDI / Freelance" quand c'est ouvert.)
    # Une AUTO-DESCRIPTION ("societe de conseil") ne suffit pas a rouvrir une
    # annonce qui affiche un salaire : il faut un B2B FORT (freelance/TJM/...).
    if has_salariat and not (has_any(blob, B2B_FORT_KW) or label_contrat):
        return "recrutement", False

    # Grosses ESN qui recrutent pour leur effectif : JAMAIS accessibles en B2B
    # (regle utilisatrice) -> gardees UNIQUEMENT si freelance/TJM explicite.
    if has_any(entite, ESN_CDI_ONLY):
        if strong and has_b2b:
            return "mission_regie", True
        return "recrutement", False

    if client_final:
        # Une BANQUE peut chercher un freelance / consultant en régie EN DIRECT,
        # mais il faut un signal FORT explicite (un mot faible incident dans une
        # annonce CDI ne suffit pas — sinon on repêche des postes internes).
        if strong and has_b2b:
            return "mission_regie", True         # régie freelance explicite -> gardé
        if strong:
            return "a_confirmer", label_contrat  # mission décrite : accessible B2B ?
        return "recrutement", False              # sinon = recrutement interne (CDI)

    if strong or weak:
        return "mission_regie", True             # cabinet + vocabulaire régie

    # Un pitch carriere ("nos valeurs", "rejoignez-nous") est du MARKETING RH,
    # PAS une preuve de salariat : presque toute plaquette de cabinet en a un.
    # Si la structure est accessible en B2B (societe de conseil...) et qu'AUCUN
    # mot de salariat (CDI / salaire / mutuelle) n'apparait, on ne tranche pas
    # -> a_confirmer. Sinon on jetait des PMO bancaires parfaits sur trois mots
    # de plaquette (cas reel : "PMO banque" / Tilencia, ecarte sur "nos valeurs"
    # alors que ses missions copiaient l'offre etalon — 2026-07-17).
    if career and not has_b2b:
        return "recrutement", label_contrat
    return "a_confirmer", label_contrat     # cabinet sans vocabulaire régie


def detect_banque(poste, texte, entite):
    blob = f"{poste} {texte} {entite}"
    if has_any(blob, BANK_TEXT_KW) or BANK_WORD_RE.search(blob):
        # garde-fou : contexte 'finance' non bancaire (crédit d'impôt, CIR...)
        if has_any(blob, BANK_NEG_KW) and not has_any(blob, STRONG_BANK_KW):
            return "NON"
        # garde-fou : plaquette d'ESN qui enumere ses secteurs (cf. supra).
        # On ne l'applique QUE si rien d'autre n'atteste le bancaire : ni le
        # titre, ni un terme bancaire SPECIFIQUE (core banking, SEPA, CIB...).
        specifiques = [k for k in BANK_TEXT_KW if k not in BANK_GENERIC_KW]
        if (not _BANQUE_RE.search(poste or "")
                and not has_any(blob, specifiques)
                and not BANK_WORD_RE.search(blob)
                and _banque_seulement_enumeration(blob)):
            return "NON"
        return "OUI"
    if has_any(entite, BANK_PROBABLE_CABINETS):
        # cabinet banque, mais si le secteur client est explicitement non-bancaire
        # (fiche lue : retail, télécom, industrie...) -> NON.
        if has_any(blob, NON_BANK_SECTOR_KW):
            return "NON"
        return "PROBABLE"
    return "NON"


def detect_domaine(poste, texte):
    """Décision sur le TITRE (le corps ne sert qu'à confirmer), en 3 étages :

    1. EXCLUSION DURE  -> paiement/monétique, urbanisation/projet SI, cyber,
       réseau, infra, prod, support : hors périmètre quoi qu'il arrive.
    2. DATA/BI = CŒUR MÉTIER -> prioritaire : un 'Data Engineer Teradata' est
       gardé alors qu'un 'Développeur Java' est écarté.
    3. EXCLUSION TECHNIQUE -> dev / stacks / outils métier (Java, Murex, COBOL...).
    Sinon : PMO / AMOA / BA / PO = domaine OK.
    """
    # 1) Exclusions dures (titre)
    if has_any(poste, EXCLUS_HARD_KW):
        return False, False, True

    # 1bis) PAIEMENT DANS LE TEXTE : DESACTIVE le 2026-07-20. Le paiement /
    # monetique est desormais un pole metier valide (decision tuteurs) -> on ne
    # jette plus une mission parce que son sujet est le paiement. (PAIEMENT_FORT_KW
    # et PAIEMENT_TEXTE_KW conserves comme documentation, plus utilises ici.)

    # 1ter) EMPILEMENT DE CERTIFICATIONS SI (cf. CERTIF_SI_KW) : profil certifiant,
    # pas une mission -> hors perimetre.
    if sum(1 for k in CERTIF_SI_KW
           if has_any(f"{poste} {texte}", [k])) >= SEUIL_CERTIF:
        return False, False, True

    # 1quater) DISPOSITIFS FISCAUX REGLEMENTAIRES (cf. FINANCE_REG_TEXTE_KW) dans
    # le texte -> finance metier fiscal, hors perimetre.
    if has_any(texte, FINANCE_REG_TEXTE_KW):
        return False, False, True

    # 2) Data/BI dans le titre => cœur métier, gardé même si techno citée
    coeur_t = has_any(poste, COEUR_METIER_KW)
    dok_t = has_any(poste, DOMAINE_OK_KW)
    if coeur_t:
        return True, dok_t, False

    # 3) Dev / stack technique (sans data) => hors périmètre
    if has_any(poste, EXCLUS_TECH_KW):
        return False, False, True

    coeur = has_any(texte, COEUR_METIER_KW)
    dok = dok_t or has_any(texte, DOMAINE_OK_KW)
    hors = not (coeur or dok)          # aucun domaine cible => hors périmètre
    return coeur, dok, hors


def fenetre_from_age(age, cloturee, republie, nb_cand=None, open_confirme=False):
    """§5 — fenêtre provisoire (avant prise en compte du vivier, cross-pass).
    - nb_candidats sert de proxy à la republication (peu de candidats = réactivée).
    - open_confirme : la source (flux ATS) ne liste QUE des postes ouverts, donc
      l'ancienneté ne disqualifie pas (au pire ROUVERTE)."""
    if cloturee:
        return "ÉCARTÉE (clôturée)"
    if age is None:
        return "OUVERTE" if open_confirme else "INCONNUE"
    if age <= 7:
        return "NOUVEAU"
    if age <= 21:
        return "OUVERTE"
    if republie:
        return "ROUVERTE"
    # PLAFOND D'AGE : 21 JOURS (regle utilisatrice 2026-07-19, explicite —
    # "pas plus de 21 jours"). Le proxy "peu de candidats = annonce reactivee"
    # autorisait jusqu'a 180 j, puis 45 j : il laissait passer des annonces de
    # plusieurs mois (cas signale : "CHEF DE PROJET AMOA TITRE" chez BROME,
    # 142 j). Au-dela de 21 j on tombe donc en AGEE, sauf republication
    # EXPLICITE (traitee juste au-dessus), qui est une vraie preuve de
    # fraicheur. Le proxy nb_candidats n'a plus lieu d'etre : tout ce qui est
    # <= 21 j est deja sorti en NOUVEAU / OUVERTE.
    #
    # NB : cela ne change PAS le sens de l'etoile dans l'Excel. Le ★ signale
    # une offre NOUVELLEMENT SCRAPEE (jamais vue lors des runs precedents),
    # meme si sa date de publication n'est pas du jour -- c'est ce que veut
    # l'utilisatrice ; le plafond 21 j garantit juste qu'elle reste recente.
    # >21 j : un flux ATS liste souvent un long archivage -> on borne à 90 j
    # (encore listé = VIVIER / candidature spontanée), au-delà = trop ancien.
    if open_confirme and age <= 90:
        return "VIVIER"
    return "AGEE"          # >21 sans signal de fraîcheur : vivier OU écartée


def classifier(annonce, today=None):
    """Classe UNE annonce. Renvoie l'annonce enrichie (nouveau dict)."""
    today = today or dt.date.today().isoformat()
    # Nettoyage des caracteres invisibles UNE SEULE FOIS ici (pas dans le chemin
    # chaud _pad) : protege toutes les detections d'un "T y p e : ‎ Stage" & co.
    poste = _strip_invisibles(annonce.get("poste", ""))
    texte = _strip_invisibles(annonce.get("texte", "") or "")
    entite = _strip_invisibles(annonce.get("entite", ""))
    emploi_label = annonce.get("emploi_label", "")

    ville = annonce.get("ville", "") or annonce.get("lieu", "")
    typ, regie_signal = detect_type(poste, texte, entite, emploi_label)
    banque = detect_banque(poste, texte, entite)
    coeur, dok, hors_domaine = detect_domaine(poste, texte)
    # Hors France+Maroc -> ecarte (cf. hors_geographie).
    if hors_geographie(poste, ville):
        coeur, dok, hors_domaine = False, False, True
    # Entite mise en liste noire par l'utilisatrice (cf. ENTITES_ECARTEES).
    if has_any(entite, ENTITES_ECARTEES):
        coeur, dok, hors_domaine = False, False, True
    date_iso, age, date_src = parse_date(annonce, today)
    cloturee = bool(annonce.get("cloturee"))
    republie = bool(annonce.get("republication"))
    nb_cand = parse_applicants(annonce)
    fenetre = fenetre_from_age(age, cloturee, republie, nb_cand,
                               bool(annonce.get("open_confirme")))

    out = dict(annonce)
    out.update({
        "type": typ,
        "regie_signal": regie_signal,
        "banque": banque,
        "coeur_metier": coeur,
        "domaine_ok": dok,
        "hors_domaine": hors_domaine,
        "date_pub_iso": date_iso,
        "date_source": date_src,
        "age_jours": age,
        "nb_candidats_int": nb_cand,
        "cloturee": cloturee,
        "republie": republie,
        "fenetre": fenetre,
        "norm_title": normalize_title(poste),
        "signature": title_signature(poste),
        "question_b2b": QUESTION_B2B if typ == "a_confirmer" else "",
        "multi_esn": False,
        "multi_esn_groupe": "",
    })
    return out


# ------------------------------------------------------------- VERDICT (unit)
def verdict_of(a):
    """Verdict + motif à partir d'une annonce déjà classée (fenêtre finalisée)."""
    banque, typ = a["banque"], a["type"]
    fen = a["fenetre"]
    ouverte = fen in ("NOUVEAU", "OUVERTE", "ROUVERTE")

    # Exclusions (ordre : domaine -> banque -> CDI -> clôture -> âge)
    if a["hors_domaine"]:
        return "ÉCARTÉE", "hors domaine"
    if banque == "NON":
        return "ÉCARTÉE", "hors banque"
    if typ == "recrutement":
        return "ÉCARTÉE", "CDI / recrutement interne"
    if fen == "ÉCARTÉE (clôturée)":
        return "ÉCARTÉE", "clôturée"
    if fen == "VIVIER":
        return "VIVIER", "besoin récurrent du cabinet"
    if fen in ("AGEE", "INCONNUE"):
        return "ÉCARTÉE", ("âge" if fen == "AGEE" else "date inconnue")

    # Ici : banque OUI/PROBABLE, domaine OK, type régie/à confirmer, fenêtre ouverte
    if typ == "mission_regie" and a["coeur_metier"]:
        return "★★ MATCH CŒUR", ""
    if typ == "mission_regie" and a["domaine_ok"]:
        return "★ À SAISIR", ""
    if typ == "a_confirmer":
        if banque == "PROBABLE" and ouverte:
            return "★ À SAISIR", ""
        return "À CONFIRMER", ""
    # mission_regie sans domaine identifié (rare)
    return "★ À SAISIR", ""


# ----------------------------------------------------------------- CROSS-PASS
VERDICT_ORDER = {"★★ MATCH CŒUR": 0, "★ À SAISIR": 1, "À CONFIRMER": 2,
                 "VIVIER": 3, "ÉCARTÉE": 4}


def dedup_annonces(annonces):
    """Retire les doublons exacts (même cabinet + même titre + même début de
    texte) — LinkedIn renvoie parfois 2 fois la même offre. Conserve l'URL."""
    seen, out = set(), []
    for a in annonces:
        key = (strip_accents(a.get("entite", "")).lower().strip(),
               normalize_title(a.get("poste", "")),
               (a.get("texte", "") or "")[:150].strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def entites_sans_regie(annonces, seuil=3):
    """FILET DE SECURITE (2026-07-17). L'ensemble des annonces d'une entite EST
    son ATS : si elle publie >= `seuil` annonces et qu'AUCUNE ne porte le
    moindre signal freelance / regie / B2B, elle ne place pas en regie -- c'est
    un recruteur CDI, inaccessible a CFConsulting.

    Ne pas dependre d'une liste ecrite a la main (ESN_CDI_ONLY) : ce filet
    aurait attrape Aubay tout seul. Le seuil de 3 evite de condamner un cabinet
    sur une ou deux annonces mal redigees.
    """
    stats = {}
    for a in annonces:
        e = strip_accents(a.get("entite") or "").lower().strip()
        if not e:
            continue
        blob = f"{a.get('poste','')} . {a.get('texte','')}"
        signal = (has_any(blob, STRONG_REGIE_KW) or has_any(blob, WEAK_REGIE_KW)
                  or bool(REF_RE.search(blob)) or has_any(blob, B2B_ACCESS_KW))
        n, s = stats.get(e, (0, 0))
        stats[e] = (n + 1, s + bool(signal))
    return {e for e, (n, s) in stats.items() if n >= seuil and s == 0}


def classify_all(annonces, today=None):
    """Classe toutes les annonces + signaux croisés (multi_esn, vivier) + verdict."""
    today = today or dt.date.today().isoformat()
    annonces = dedup_annonces(annonces)
    items = [classifier(a, today) for a in annonces]

    # --- Filet de securite : entites qui ne publient JAMAIS de regie (cf. supra)
    jamais_regie = entites_sans_regie(annonces)
    for a in items:
        if strip_accents(a["entite"]).lower().strip() in jamais_regie:
            a["type"] = "recrutement"
            a["regie_signal"] = False

    # --- Vivier (§5) : un cabinet qui republie >=2 fois un titre similaire
    counts = {}
    for a in items:
        key = (strip_accents(a["entite"]).lower().strip(), a["norm_title"])
        counts[key] = counts.get(key, 0) + 1
    for a in items:
        key = (strip_accents(a["entite"]).lower().strip(), a["norm_title"])
        recurrent = a["norm_title"] and counts.get(key, 0) >= 2
        if a["fenetre"] == "AGEE":
            # On ne promeut en VIVIER qu'un besoin récurrent RÉCENT (<=90 j) :
            # évite de ressusciter l'archive ancienne d'un flux ATS.
            young = a["age_jours"] is not None and a["age_jours"] <= 90
            a["fenetre"] = "VIVIER" if (recurrent and young) else "AGEE"
        a["besoin_recurrent"] = bool(recurrent)

    # --- Multi-ESN (§6) : 2 CABINETS différents publient LA MÊME mission
    #     (>=2 tokens métier partagés) à moins de 15 jours d'écart.
    #     On exclut les clients finaux (une banque qui recrute pour elle-même
    #     ne « consulte pas plusieurs ESN »).
    def eligible_multi(a):
        return (a["type"] in ("mission_regie", "a_confirmer")
                and len(a["signature"]) >= 2)

    grp = 0
    for i in range(len(items)):
        ai = items[i]
        if not eligible_multi(ai) or ai.get("multi_esn"):
            continue
        matches = []
        for j in range(i + 1, len(items)):
            aj = items[j]
            if not eligible_multi(aj):
                continue
            if len(ai["signature"] & aj["signature"]) < 2:      # >=2 tokens communs
                continue
            if strip_accents(aj["entite"]).lower() == strip_accents(ai["entite"]).lower():
                continue
            if ai["age_jours"] is not None and aj["age_jours"] is not None:
                if abs(ai["age_jours"] - aj["age_jours"]) > 15:
                    continue
            matches.append(aj)
        if matches:
            grp += 1
            tag = f"G{grp}"
            ai["multi_esn"] = True
            ai["multi_esn_groupe"] = tag
            for aj in matches:
                aj["multi_esn"] = True
                aj["multi_esn_groupe"] = tag

    # --- Verdict final
    for a in items:
        v, motif = verdict_of(a)
        a["verdict"] = v
        a["motif"] = motif

    items.sort(key=lambda a: (VERDICT_ORDER.get(a["verdict"], 9),
                              a["age_jours"] if a["age_jours"] is not None else 9999))
    return items
