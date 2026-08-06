# -*- coding: utf-8 -*-
"""Point d'entrée pour l'exécution depuis GitHub Actions.

N'existe QUE pour le cloud : l'exécution locale continue de passer par
`python linkedin_sourcing_regie.py both` directement, sur les fichiers
locaux — rien ne change dans votre usage habituel.

Séquence :
  1. Télécharge l'état (Excel de travail + caches JSON) depuis Google Drive.
  2. Lance le pipeline existant tel quel (mêmes fichiers locaux que d'habitude,
     `update_excel` ne touche jamais aux lignes déjà présentes).
  3. Renvoie l'état mis à jour vers Google Drive.
  4. Envoie le mail de notification (repli Python de run_daily.ps1).

Ne fait AUCUNE hypothèse sur un run précédent : si Drive n'a encore aucun
fichier (premier run), le pipeline démarre à vide — comportement déjà géré
partout ailleurs (caches absents = listes vides)."""
import os
import re
import subprocess
import sys

import drive_sync as DRIVE
import send_mail

XLSX = "Sourcing_regie_banque.xlsx"
FICHIERS_ETAT = [
    XLSX,
    "annonces_vues.json",
    "cache_gemini.json",
    "cache_annonces_maroc.json",
    "cache_annonces_france.json",
]


def main():
    print("=== Synchronisation Drive (avant le run) ===")
    for nom in FICHIERS_ETAT:
        DRIVE.download(nom, nom)

    print("\n=== Lancement du pipeline ===")
    result = subprocess.run(
        [sys.executable, "linkedin_sourcing_regie.py", "both"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    sortie = (result.stdout or "") + (result.stderr or "")
    print(sortie)
    exit_code = result.returncode

    print("\n=== Synchronisation Drive (après le run) ===")
    for nom in FICHIERS_ETAT:
        DRIVE.upload(nom, nom)

    matches = re.findall(r"===>[^\n]*", sortie)
    resume = matches[-1].strip() if matches else (
        "Scraping OK (voir les logs GitHub Actions)." if exit_code == 0
        else f"ÉCHEC du scraping (exit={exit_code}) — voir les logs GitHub Actions.")
    statut = "réussie" if exit_code == 0 else "échouée"

    print("\n=== Envoi du mail ===")
    send_mail.envoyer_notification(XLSX, statut, resume)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
