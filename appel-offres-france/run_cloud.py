# -*- coding: utf-8 -*-
"""Point d'entrée pour l'exécution depuis GitHub Actions (veille appels
d'offres publics France — BOAMP/APProch/PLACE).

N'existe QUE pour le cloud : l'exécution locale continue de passer par les
3 scripts (run_collect.py / run_download.py / run_synthesis.py) directement,
sur les fichiers locaux.

Séquence :
  1. Télécharge l'Excel de travail depuis Google Drive (OBLIGATOIRE : il est
     censé déjà exister, cf. drive_sync.py — jamais de redémarrage à zéro
     silencieux, même logique de sécurité que sourcing-regie-banque).
  2. Lance les 3 étapes existantes, dans l'ordre, SANS LES MODIFIER (même
     dédoublonnage par identifiant que `excel_writer.py`).
  3. Renvoie l'Excel mis à jour vers Google Drive.

Pas d'envoi de mail pour ce projet (demande explicite)."""
import subprocess
import sys

import drive_sync as DRIVE

EXCEL = "data/veille_appels_offres.xlsx"

ETAPES = [
    ["run_collect.py", "--adaptee"],
    ["run_download.py"],
    ["run_synthesis.py", "--provider", "gemini"],
]


def main():
    print("=== Synchronisation Drive (avant le run) ===")
    DRIVE.download(EXCEL, EXCEL, obligatoire=True)

    exit_code = 0
    for etape in ETAPES:
        print(f"\n=== Étape : {' '.join(etape)} ===")
        result = subprocess.run([sys.executable] + etape)
        if result.returncode != 0:
            print(f"  ! {etape[0]} a échoué (exit={result.returncode}) — "
                  f"on continue avec les étapes suivantes (best-effort).")
            exit_code = 1

    print("\n=== Synchronisation Drive (après le run) ===")
    DRIVE.upload(EXCEL, EXCEL)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
