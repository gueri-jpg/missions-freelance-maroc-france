from classifier import detect_domaine

titles = [
    'Chef de projet Infrastructure Réseaux',
    'Chef de projet SI (H/F)',
    'Data Scientist / MLOps',
    'Chargé de recette / homologation SI bancaire',
]

from classifier import has_any, SIGNAL_PILOTAGE_KW, EXCLUS_SI_SEUL_KW, detect_domaine
for poste in titles:
    texte = 'Mission freelance client bancaire. TJM.'
    blob = f"{poste} {texte}"
    print(poste)
    print('  EXCLUS_SI_SEUL substr:', [k for k in EXCLUS_SI_SEUL_KW if k in blob.lower()])
    print('  SIGNAL_PILOTAGE substr:', [k for k in SIGNAL_PILOTAGE_KW if k in blob.lower()])
    print('  EXCLUS_SI_SEUL has_any:', has_any(blob, EXCLUS_SI_SEUL_KW))
    print('  SIGNAL_PILOTAGE has_any:', has_any(blob, SIGNAL_PILOTAGE_KW))
    print('  detect_domaine =>', detect_domaine(poste, texte))
