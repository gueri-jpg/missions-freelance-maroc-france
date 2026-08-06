# -*- coding: utf-8 -*-
"""Test rapide (~1-2 min) de la tuyauterie cloud — Drive, Gemini, SMTP — SANS
lancer le scraping complet (45-70 min). Sert uniquement à valider la
configuration (secrets, partage Drive) avant de compter sur le run réel.

Usage : python test_cloud_setup.py
"""
import os
import sys

import drive_sync as DRIVE

TMP_DL = "_test_drive_download.xlsx"


def test_drive():
    print("--- Test Google Drive (lecture seule, rien n'est modifié) ---")
    ok = DRIVE.download("Sourcing_regie_banque.xlsx", TMP_DL)
    if not ok:
        print("  ÉCHEC : fichier introuvable dans GDRIVE_FOLDER_ID, ou accès refusé "
              "(vérifiez le partage avec le compte de service).")
        return False
    taille = os.path.getsize(TMP_DL)
    os.remove(TMP_DL)
    print(f"  OK : fichier trouvé et téléchargé ({taille} octets).")
    return True


def test_gemini():
    print("--- Test Gemini ---")
    try:
        import similarite as SIM
        rep = SIM._gemini_generate("Réponds uniquement le mot OK.")
        print(f"  OK : réponse reçue ({rep.strip()[:50]!r}).")
        return True
    except Exception as e:
        print(f"  ÉCHEC : {e}")
        return False


def test_smtp():
    print("--- Test SMTP (envoi d'un mail réel, marqué TEST) ---")
    try:
        import send_mail
        send_mail.envoyer_notification(
            None, "TEST — vérification config cloud (aucun scraping lancé)",
            "Ceci est un mail de test envoyé par le workflow GitHub Actions "
            "pour vérifier la configuration SMTP. Aucune donnée réelle n'a "
            "été scrapée pendant ce test.")
        return True
    except Exception as e:
        print(f"  ÉCHEC : {e}")
        return False


def main():
    tester_smtp = os.environ.get("TEST_SMTP", "1") != "0"
    resultats = {"Google Drive": test_drive(), "Gemini": test_gemini()}
    if tester_smtp:
        resultats["SMTP"] = test_smtp()

    print("\n=== RÉSUMÉ ===")
    tout_ok = True
    for nom, ok in resultats.items():
        print(f"  {'OK' if ok else 'ÉCHEC'}  {nom}")
        tout_ok = tout_ok and ok
    sys.exit(0 if tout_ok else 1)


if __name__ == "__main__":
    main()
