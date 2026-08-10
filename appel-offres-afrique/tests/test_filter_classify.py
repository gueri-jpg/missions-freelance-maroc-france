import datetime as dt

import filter_classify as fc


def test_classify_domain_it_fort():
    record = {"objet": "Développement d'une application mobile de gestion", "acheteur": "Mairie"}
    assert fc.classify_domain(record) == "IT confirmé"


def test_classify_domain_acquisition_materielle_exclue():
    record = {"objet": "Acquisition de matériels informatiques pour les services", "acheteur": "Ministère"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_amoa_sans_contexte_it_hors_it():
    record = {"objet": "Assistance à maîtrise d'ouvrage pour la construction d'un pont", "acheteur": "Conseil régional"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_amoa_avec_contexte_it_confirme():
    record = {"objet": "AMOA pour la refonte du système d'information RH", "acheteur": "Ministère"}
    assert fc.classify_domain(record) == "IT confirmé"


def test_classify_domain_btp_exclu():
    record = {"objet": "Travaux de construction et réhabilitation de voirie", "acheteur": "Mairie"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_aucun_signal_a_verifier():
    record = {"objet": "Recrutement d'un consultant pour un audit financier", "acheteur": "Ministère"}
    assert fc.classify_domain(record) == "à vérifier"


def test_is_pure_fourniture_exclut_fourniture():
    assert fc.is_pure_fourniture({"type_marche": "FOURNITURE"}) is True


def test_is_pure_fourniture_garde_service():
    assert fc.is_pure_fourniture({"type_marche": "Services"}) is False


def test_is_pure_fourniture_garde_type_absent():
    assert fc.is_pure_fourniture({"type_marche": ""}) is False


def test_is_deadline_too_soon_date_passee():
    today = dt.date(2026, 8, 3)
    assert fc.is_deadline_too_soon({"date_limite": "2023-01-01"}, today=today) is True


def test_is_deadline_too_soon_date_future_ok():
    today = dt.date(2026, 8, 3)
    assert fc.is_deadline_too_soon({"date_limite": "2026-12-31"}, today=today) is False


def test_is_deadline_too_soon_date_absente_jamais_exclue():
    assert fc.is_deadline_too_soon({"date_limite": None}) is False


def test_is_deadline_too_soon_format_jj_mm_aaaa():
    today = dt.date(2026, 8, 3)
    assert fc.is_deadline_too_soon({"date_limite": "17-04-2026"}, today=today) is True
    assert fc.is_deadline_too_soon({"date_limite": "17-04-2027"}, today=today) is False


def test_classify_domain_maintenance_nue_pas_it_confirme():
    """Non-régression : 'informatique' seul ne doit plus jamais suffire à
    classer 'IT confirmé' un marché de pure maintenance/entretien."""
    record = {"objet": "Maintenance du parc informatique de la mairie", "acheteur": "Mairie"}
    assert fc.classify_domain(record) != "IT confirmé"


def test_classify_domain_entretien_materiel_pas_it_confirme():
    record = {"objet": "Entretien des équipements informatiques", "acheteur": "Ministère"}
    assert fc.classify_domain(record) != "IT confirmé"


def test_classify_domain_maintenance_avec_developpement_a_verifier():
    """Un vrai signal IT fort (développement logiciel) présent en même temps
    que 'maintenance' doit rester repêchable ('à vérifier'), pas hors IT dur."""
    record = {"objet": "Développement logiciel et maintenance évolutive de l'outil", "acheteur": "Ministère"}
    assert fc.classify_domain(record) == "à vérifier"


def test_classify_domain_amoa_developpement_web_it_confirme():
    record = {"objet": "AMOA pour le développement d'un site web institutionnel", "acheteur": "Ministère"}
    assert fc.classify_domain(record) == "IT confirmé"


def test_classify_domain_amoa_business_intelligence_it_confirme():
    record = {"objet": "Assistance à maîtrise d'ouvrage pour un projet de Business Intelligence", "acheteur": "X"}
    assert fc.classify_domain(record) == "IT confirmé"


def test_classify_domain_amoa_application_mobile_it_confirme():
    record = {"objet": "AMO pour le développement d'une application mobile de suivi", "acheteur": "X"}
    assert fc.classify_domain(record) == "IT confirmé"


def test_classify_domain_ivoirienne_ne_declenche_pas_voirie():
    """Non-régression : 'voirie' (exclusion BTP) est une sous-chaîne de
    'ivoirienne'/'ivoirien' — ne doit plus jamais matcher par accident."""
    record = {"objet": "Développement logiciel pour l'administration ivoirienne"}
    assert fc.classify_domain(record) == "IT confirmé"


def test_contains_keyword_pluriel_optionnel():
    assert fc._contains_keyword("acquisition de matériels", ["matériel"]) is True
    assert fc._contains_keyword("ivoirienne", ["voirie"]) is False


def test_is_montant_too_high_exclut_au_dela_du_seuil():
    assert fc.is_montant_too_high({"montant_estime_valeur": 1_500_000}) is True
    assert fc.is_montant_too_high({"montant_estime_valeur": 500_000}) is False


def test_is_montant_too_high_absent_jamais_exclu():
    assert fc.is_montant_too_high({}) is False
    assert fc.is_montant_too_high({"montant_estime_valeur": None}) is False


def test_classify_domain_centre_culturel_hors_it():
    record = {"objet": "SELECTION D'UNE ASSOCIATION QUALIFIEE POUR LA GESTION DU CENTRE D'EPANOUISSEMENT ARTISTIQUE ET LITTERAIRE DU CENTRE CULTUREL DES JEUNES"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_captation_retransmission_hors_it():
    record = {"objet": "La captation et la retransmission des courses marocaines pour l'année 2026"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_hebergement_seul_hors_it():
    record = {"objet": "La réalisation de la prestation d'Hébergement du Portail du Centre Hospitalo-universitaire"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_hebergement_avec_developpement_a_verifier():
    """Un vrai signal IT fort co-présent avec 'hébergement' reste
    repêchable ('à vérifier'), pas hors IT dur."""
    record = {"objet": "Développement logiciel et hébergement de la plateforme"}
    assert fc.classify_domain(record) == "à vérifier"


def test_classify_domain_gardiennage_hors_it():
    """Constaté en direct (ONDA) : sans pré-filtre de domaine côté source,
    ces prestations génériques de service tombaient à tort en 'à vérifier'."""
    record = {"objet": "Prestations de gardiennage et de surveillance de l'Aéropôle de l'Aéroport Casablanca Mohammed V"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_nettoyage_hors_it():
    record = {"objet": "Nettoyage et activités connexes des locaux de l'aéroport d'Ifrane"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_nettoyage_avec_base_de_donnees_a_verifier():
    """'nettoyage' peut aussi désigner du nettoyage/dédoublonnage de
    données (BI/qualité de données) — un vrai signal IT fort co-présent
    reste repêchable, pas hors IT dur."""
    record = {"objet": "Nettoyage et dédoublonnage de la base de données clients"}
    assert fc.classify_domain(record) == "à vérifier"


def test_classify_domain_collecte_dechets_hors_it():
    """Libellé réel constaté (ONDA, N°111) : l'énumération 'débris, déchets et
    ordures' casse la contiguïté d'une locution figée comme 'collecte des
    déchets' — d'où l'usage de mots isolés dans MOTS_EXCLUSION plutôt qu'une
    locution complète (régression réelle rencontrée en direct)."""
    record = {"objet": "Prestations de collecte des débris, des déchets et des ordures et activités connexes de l'Aéroport Rabat-Salé"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_climatisation_hors_it():
    record = {"objet": "Fourniture, installation et mise en service d'un système de climatisation pour les salles techniques"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_formation_certification_reseau_hors_it():
    """Cas réel ayant motivé la construction du collecteur ONDA — revu après
    coup : dispenser une formation/certification (même RedHat/CISCO) est un
    métier de centre de formation, pas du développement/BI/conseil, même si
    le sujet est techniquement de l'IT. Hors scope, demandé explicitement."""
    record = {"objet": (
        "Réalisation des actions de formation techniques au profit du personnel : "
        "Lot 1 : Formation RED Hat System Administration Lot 2 : Formation et certification CISCO"
    )}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_formation_seule_hors_it():
    record = {"objet": "Organisation d'une session de formation en secourisme au profit du personnel"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_formation_avec_developpement_a_verifier():
    """Un vrai signal IT fort co-présent (ex. un module e-learning développé
    sur mesure) reste repêchable, pas hors IT dur — même logique que
    maintenance/hébergement."""
    record = {"objet": "Développement d'un module e-learning de formation aux outils de Business Intelligence"}
    assert fc.classify_domain(record) == "à vérifier"


def test_classify_domain_formation_ne_matche_pas_information():
    """'formation' ne doit jamais matcher par sous-chaîne à l'intérieur de
    'information'/'système d'information' — même principe que le bug
    voirie/ivoirienne déjà corrigé (limite de mot, pas sous-chaîne brute).
    Texte sans 'abonnement' pour isoler ce seul point (cf. tests dédiés
    à 'abonnement' plus bas, qui EUX doivent classer hors IT)."""
    record = {"objet": "Un service de supervision de la sécurité des systèmes d'information"}
    assert fc.classify_domain(record) != "hors IT"


def test_classify_domain_abonnement_seul_hors_it():
    """Cas réel constaté (PMMP) : un abonnement à un service (même de
    supervision/sécurité SI) est un engagement récurrent de type 'run',
    pas une mission de conseil/dev/BI — même logique que hébergement."""
    record = {"objet": "L'abonnement à un service de Supervision et de Surveillance de la Sécurité des Systèmes d'Information"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_datacenter_hors_it():
    """Cas réel constaté (PMMP) : externaliser vers un datacenter est un
    sujet d'infrastructure/hosting, pas de conseil applicatif, même en
    tournure 'Assistance à l'externalisation...' (AMOA-like)."""
    record = {"objet": "Assistance à l'externalisation du projet Portail des usagers de l'eau vers un datacenter souverain"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_datacenter_ne_matche_pas_projet_data():
    """Demandé explicitement : 'datacenter'/'data center' est un mot/une
    locution complète (limite de mot) — ne doit jamais matcher par
    sous-chaîne le simple mot 'data' isolé ('projet Data', 'Data Lake',
    'Big Data', 'Data Scientist'...), qui sont des sujets BI/data legitimes,
    pas de l'infrastructure/hosting. Vérifié en direct sur des libellés
    réalistes."""
    objets_data_legitimes = [
        "Assistance à la mise en œuvre du programme Data de l'entreprise",
        "Développement d'une plateforme Data et Intelligence Artificielle",
        "Mise en place d'un Data Lake pour l'analyse des données clients",
        "Étude de faisabilité pour un projet Big Data",
        "Conception et mise en œuvre d'un Data Warehouse décisionnel",
        "Recrutement d'un Data Scientist pour le programme data",
    ]
    for objet in objets_data_legitimes:
        assert fc.classify_domain({"objet": objet}) != "hors IT", objet
        assert not fc._contains_keyword(objet.lower(), ["datacenter", "data center"]), objet


def test_classify_domain_capsules_video_hors_it():
    """Cas réel constaté (PMMP) : production de contenu audiovisuel, même
    généralisation que captation/retransmission. 'capsules' (pluriel du
    premier mot) doit aussi matcher, pas seulement 'capsule'."""
    record = {"objet": "Achat et production de capsules vidéo en IA pour le compte de la SOREC ; en lot unique."}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_renouvellement_des_licences_pluriel_hors_it():
    """Cas réel constaté (PMMP) : 'renouvellement DES licences' (article
    pluriel) ne matchait ni 'renouvellement de licence' ni 'renouvellement
    de licences' (article singulier) — locution complète, distincte."""
    record = {"objet": (
        "Renouvellement des licences de la solution de gestion financière pour les besoins "
        "de la Société Nationale de Radiodiffusion et de Télévision. (pour la conclusion "
        "d'un marché reconductible)"
    )}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_location_licences_exclue():
    record = {"objet": "Location des licences d'utilisation des logiciels informatiques, en lot unique"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_ignore_le_nom_de_lacheteur():
    """Non-régression du bug SNDI : le nom de l'acheteur ("Société Nationale
    de Développement Informatique") ne doit jamais faire basculer un objet
    sans rapport (achat de véhicules) vers 'IT confirmé'."""
    record = {"objet": "ACQUISITION DE VEHICULES POUR LA SNDI", "acheteur": "Société Nationale de Développement Informatique"}
    assert fc.classify_domain(record) != "IT confirmé"


def test_is_pure_fourniture_libelle_detaille_ppm_ci():
    """Le PPM Côte d'Ivoire utilise des libellés détaillés, pas les
    catégories brutes — doit matcher par préfixe, pas égalité stricte."""
    assert fc.is_pure_fourniture({"type_marche": "Fourniture de véhicule"}) is True
    assert fc.is_pure_fourniture({"type_marche": "Fourniture informatiques"}) is True
    assert fc.is_pure_fourniture({"type_marche": "Fourniture de bureaux"}) is True
    assert fc.is_pure_fourniture({"type_marche": "Prestation intellectuelle"}) is False


def test_classify_domain_acquisition_plateforme_exclue():
    record = {"objet": "Acquisition d’une plateforme générative et agentique AI et mise en œuvre du portefeuille"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_acquisition_infrastructure_exclue():
    record = {"objet": "Acquisition, installation et mise en service d'une infrastructure d'intelligence artificielle"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_souscription_licences_exclue():
    record = {"objet": "La souscription des licences Microsoft pour la plateforme serveur"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_amo_seul_hors_it():
    """'AMO' seul (hors 'AMOA') est aussi un métier transversal (AMO
    travaux/bâtiment...) — ambigu, jamais suffisant seul pour confirmer l'IT."""
    record = {"objet": "Mission d'AMO pour la construction du siège régional"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_amo_avec_systeme_information_it_confirme():
    """'système d'information' est un terme FORT à lui seul (pas seulement
    contexte) — la présence d'AMO en plus ne change rien, cohérent avec le
    comportement déjà établi pour 'AMOA système d'information'."""
    record = {"objet": "Mission d'AMO pour le déploiement du système d'information"}
    assert fc.classify_domain(record) == "IT confirmé"


def test_classify_domain_pmo_seul_hors_it():
    record = {"objet": "Recrutement d'un PMO pour le programme d'infrastructure routière"}
    assert fc.classify_domain(record) == "hors IT"


def test_classify_domain_pmo_it_confirme():
    """Cas explicitement demandé : 'PMO' + contexte IT ('numérique') doit
    être repêché, pas ignoré — combo AMBIGUS+CONTEXTE traité par
    _has_it_keyword comme un signal IT à part entière (même mécanisme que
    'AMOA' + contexte, pas une classe à part avec un statut plus faible)."""
    record = {"objet": "Recrutement d'un PMO IT pour le programme de transformation numérique"}
    assert fc.classify_domain(record) == "IT confirmé"


def test_classify_domain_web_development_anglais_confirme():
    record = {"objet": "Provision of Web Development Services for the corporate portal"}
    assert fc.classify_domain(record) == "IT confirmé"


def test_classify_domain_cybersecurity_anglais_confirme():
    record = {"objet": "Provision of Cybersecurity Solution for the regional office"}
    assert fc.classify_domain(record) == "IT confirmé"


def test_classify_domain_cleaning_services_anglais_reste_a_verifier():
    """Limite connue et documentée (README) : 'cleaning' n'a pas
    d'équivalent dans MOTS_EXCLUSION (français uniquement) — ne doit
    cependant jamais être classé IT confirmé."""
    record = {"objet": "Provision of Cleaning Services for the country office"}
    assert fc.classify_domain(record) != "IT confirmé"


def test_filter_and_classify_exclut_hors_it_et_trie():
    records = [
        {"objet": "Achat de matériel informatique", "acheteur": "X", "date_limite": "2026-12-31"},
        {"objet": "Développement logiciel de gestion", "acheteur": "X", "date_limite": "2026-12-31"},
        {"objet": "AMOA système d'information", "acheteur": "X", "date_limite": "2026-12-31"},
    ]
    result = fc.filter_and_classify(records)
    assert len(result) == 2
    assert result[0]["domaine"] == "IT confirmé"
