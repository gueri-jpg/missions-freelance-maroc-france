# -*- coding: utf-8 -*-
"""Point d'entrée pour l'exécution depuis GitHub Actions.

N'existe QUE pour le cloud : l'exécution locale continue de passer par
`python linkedin_sourcing_regie.py both` directement, sur les fichiers
locaux — rien ne change dans votre usage habituel.

Séquence :
  1. Télécharge l'état (Excel de travail + caches JSON) depuis Google Drive.
     Le fichier Excel est OBLIGATOIRE (cf. drive_sync.download,
     obligatoire=True) : s'il est introuvable pour une vraie raison (panne,
     permissions, mauvais dossier...), on ARRÊTE ici plutôt que de laisser
     le pipeline repartir de zéro et écraser le vrai fichier sur Drive
     (incident réel du 2026-08 : tous les onglets de référence et les
     remplissages manuels perdus après une panne de téléchargement avalée
     silencieusement).
  2. Lance le pipeline existant tel quel (mêmes fichiers locaux que
     d'habitude, `update_excel` ne touche jamais aux lignes déjà présentes).
  3. Renvoie l'état mis à jour vers Google Drive.
  4. Envoie le mail de notification (repli Python de run_daily.ps1).
"""
import os
import re
import subprocess
import sys

import drive_sync as DRIVE
import send_mail

XLSX = "Sourcing_regie_banque.xlsx"
# Caches JSON : régénérables, une absence n'est jamais destructive (juste du
# retraitement en plus) — contrairement à l'Excel, ils restent optionnels.
FICHIERS_CACHE = [
    "annonces_vues.json",
    "cache_gemini.json",
    "cache_annonces_maroc.json",
    "cache_annonces_france.json",
]


def synchroniser_avant():
    """Télécharge l'état depuis Drive. Lève DriveSyncError si l'Excel de
    travail est introuvable ou inaccessible pour une vraie raison — appelant
    doit alors arrêter le run sans toucher à rien d'autre."""
    print("=== Synchronisation Drive (avant le run) ===")
    # obligatoire=True : voir le docstring du module. Ne PAS mettre False
    # "pour que ça marche au premier run" — le premier run, c'est vous qui
    # l'avez fait manuellement en uploadant le fichier sur Drive avant de
    # configurer ce workflow ; à partir de là, il doit toujours exister.
    DRIVE.download(XLSX, XLSX, obligatoire=True)
    for nom in FICHIERS_CACHE:
        try:
            DRIVE.download(nom, nom, obligatoire=False)
        except Exception as e:
            print(f"  [drive] {nom} : téléchargement échoué ({e}) — on continue "
                  f"sans (cache régénérable, pas de perte de travail humain).")


def synchroniser_apres():
    """Renvoie l'état vers Drive. Renvoie la liste des fichiers dont l'envoi
    a échoué (jamais avalé en silence — reflété dans le mail final)."""
    print("\n=== Synchronisation Drive (après le run) ===")
    echecs = []
    for nom in [XLSX] + FICHIERS_CACHE:
        try:
            DRIVE.upload(nom, nom)
        except Exception as e:
            print(f"  [drive] ERREUR envoi de {nom} : {e}")
            echecs.append(nom)
    return echecs


def main():
    try:
        synchroniser_avant()
    except Exception as e:
        print(f"\n!!! ARRÊT AVANT LE SCRAPING : {e}")
        send_mail.envoyer_notification(
            None, "ÉCHOUÉE (synchronisation Drive)",
            f"Le run a été arrêté AVANT tout scraping pour éviter d'écraser "
            f"le fichier Drive : {e}\n\nAucune donnée n'a été modifiée, ni "
            f"localement ni sur Drive.")
        sys.exit(1)

    print("\n=== Lancement du pipeline ===")
    result = subprocess.run(
        [sys.executable, "linkedin_sourcing_regie.py", "both"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    sortie = (result.stdout or "") + (result.stderr or "")
    print(sortie)
    exit_code = result.returncode

    echecs_upload = synchroniser_apres()

    matches = re.findall(r"===>[^\n]*", sortie)
    resume = matches[-1].strip() if matches else (
        "Scraping OK (voir les logs GitHub Actions)." if exit_code == 0
        else f"ÉCHEC du scraping (exit={exit_code}) — voir les logs GitHub Actions.")
    if echecs_upload:
        resume += (f"\n\nATTENTION : échec de synchronisation Drive pour "
                    f"{', '.join(echecs_upload)} — leur contenu local a été "
                    f"mis à jour mais PAS renvoyé vers Drive.")
        statut = "échouée (sync Drive)"
    else:
        statut = "réussie" if exit_code == 0 else "échouée"

    print("\n=== Envoi du mail ===")
    send_mail.envoyer_notification(XLSX, statut, resume)

    sys.exit(exit_code if not echecs_upload else 1)


if __name__ == "__main__":
    main()
