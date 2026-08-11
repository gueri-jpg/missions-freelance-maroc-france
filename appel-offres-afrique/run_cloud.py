# -*- coding: utf-8 -*-
"""Point d'entrée pour l'exécution depuis GitHub Actions (veille appels
d'offres publics IT — Côte d'Ivoire / Maroc).

N'existe QUE pour le cloud : l'exécution locale continue de passer par
`python run_collect.py` directement, sur les fichiers locaux.

Séquence :
  1. Télécharge l'Excel de travail + les caches de suivi d'IDs déjà traités
     depuis Google Drive. L'Excel est OBLIGATOIRE (censé déjà exister,
     jamais de redémarrage à zéro silencieux) ; les caches d'IDs sont
     optionnels (régénérables, juste une perte d'efficacité si absents).
  2. Lance run_collect.py tel quel (mêmes fichiers locaux, même
     dédoublonnage).
  3. Renvoie l'Excel + les caches mis à jour vers Google Drive.

Pas d'envoi de mail pour ce projet (demande explicite)."""
import os
import subprocess
import sys

import drive_sync as DRIVE

EXCEL = "data/veille_appels_offres_afrique.xlsx"
CACHES_ID = [
    "data/_ids_geres_appels_doffres.json",
    "data/_ids_geres_plans_prévisionnels.json",
]


def main():
    print("=== Synchronisation Drive (avant le run) ===")
    # Sur Drive, un fichier n'a pas de "chemin" (pas de notion de dossier
    # local) : il faut chercher par son nom seul, tout en le sauvegardant
    # localement sous data/. Confondre les deux (chercher "data/xxx.xlsx"
    # sur Drive) fait échouer la recherche à tort ("introuvable") même
    # quand le fichier existe bien.
    os.makedirs("data", exist_ok=True)
    DRIVE.download(os.path.basename(EXCEL), EXCEL, obligatoire=True)
    for nom in CACHES_ID:
        try:
            DRIVE.download(os.path.basename(nom), nom, obligatoire=False)
        except Exception as e:
            print(f"  [drive] {nom} : téléchargement échoué ({e}) — on continue "
                  f"sans (cache régénérable).")

    print("\n=== Lancement de run_collect.py ===")
    result = subprocess.run([sys.executable, "run_collect.py"])
    exit_code = result.returncode
    if exit_code != 0:
        print(f"  ! run_collect.py a échoué (exit={exit_code}).")

    print("\n=== Synchronisation Drive (après le run) ===")
    DRIVE.upload(os.path.basename(EXCEL), EXCEL)
    for nom in CACHES_ID:
        try:
            DRIVE.upload(os.path.basename(nom), nom)
        except Exception as e:
            print(f"  [drive] ERREUR envoi de {nom} : {e}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
