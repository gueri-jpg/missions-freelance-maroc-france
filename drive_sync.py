# -*- coding: utf-8 -*-
"""Synchronisation des fichiers d'état (Excel de travail + caches JSON) avec
un dossier Google Drive.

Pourquoi : le pipeline tourne depuis GitHub Actions (machine éphémère, sans
accès au PC local), mais le fichier Excel est édité manuellement en local
(surlignages, lignes supprimées, notes). Google Drive sert de source de
vérité commune : ce module télécharge l'état avant le run, la logique de
fusion existante (`update_excel`, jamais destructive) fait le reste, puis on
renvoie l'état mis à jour vers Drive.

RÈGLE DE SÉCURITÉ (incident du 2026-08) : une PANNE de téléchargement (auth,
réseau, quota, dossier introuvable...) ne doit JAMAIS être confondue avec
« le fichier n'existe pas encore ». Confondre les deux a fait, une fois,
repartir tout le pipeline de zéro et écraser le vrai fichier Drive avec un
fichier neuf, vidant l'historique, les onglets de référence de la tutrice et
tous les remplissages manuels. Donc :
  - `download()` ne renvoie False (« fichier absent, premier run ») QUE si
    Drive a répondu proprement avec zéro résultat. Toute AUTRE erreur est
    levée (exception), jamais avalée.
  - `upload()` lève aussi en cas d'échec réel, au lieu de juste l'afficher.
Charge à l'appelant (`run_cloud.py`) d'arrêter tout le run si le
téléchargement du fichier de travail principal échoue pour une vraie raison.
"""
import io
import json
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]

_SERVICE = None  # mise en cache : un seul client par process


class DriveSyncError(RuntimeError):
    """Erreur Drive réelle (pas un simple "fichier absent")."""


def _service():
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    # .strip() : un secret GitHub copié-collé peut embarquer un retour à la
    # ligne final invisible (cas réel du 2026-08 : GDRIVE_FOLDER_ID terminé
    # par \n, provoquant un "File not found" trompeur — l'ID semblait juste
    # mais la requête cherchait un dossier dont l'ID se terminait par un saut
    # de ligne). On nettoie systématiquement toute valeur venant de l'env.
    key_json = (os.environ.get("GDRIVE_SA_KEY_JSON") or "").strip()
    if not key_json:
        raise DriveSyncError("GDRIVE_SA_KEY_JSON non définie")
    info = json.loads(key_json)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    _SERVICE = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _SERVICE


def _folder_id():
    fid = (os.environ.get("GDRIVE_FOLDER_ID") or "").strip()
    if not fid:
        raise DriveSyncError("GDRIVE_FOLDER_ID non définie")
    return fid


def _find_file_id(service, name):
    """Renvoie l'ID du fichier `name` dans le dossier, ou None si Drive a
    RÉPONDU CORRECTEMENT avec zéro résultat (cas légitime : le fichier n'a
    jamais été créé). Toute erreur de requête (dossier introuvable, quota,
    auth...) lève une exception — ce n'est PAS un cas de "fichier absent"."""
    q = f"'{_folder_id()}' in parents and name = '{name}' and trashed = false"
    res = service.files().list(q=q, fields="files(id, name)", pageSize=1).execute()
    fichiers = res.get("files", [])
    return fichiers[0]["id"] if fichiers else None


def download(name, local_path, obligatoire=False):
    """Télécharge `name` depuis le dossier Drive vers `local_path`.

    Renvoie True si téléchargé, False si Drive confirme que le fichier
    n'existe pas encore (premier run — cas normal pour les caches).

    Si `obligatoire=True` (le fichier DOIT déjà exister, ex. l'Excel de
    travail après le tout premier run) et qu'il est absent, lève
    DriveSyncError : mieux vaut arrêter le pipeline que le laisser repartir
    de zéro et écraser un fichier qui contient du travail humain.

    Toute erreur RÉELLE (auth, réseau, quota, dossier introuvable) lève
    toujours une exception, qu'`obligatoire` soit vrai ou non — ce n'est
    jamais une raison légitime de continuer comme si de rien n'était."""
    service = _service()
    file_id = _find_file_id(service, name)
    if not file_id:
        if obligatoire:
            raise DriveSyncError(
                f"{name} est introuvable dans le dossier Drive (GDRIVE_FOLDER_ID) "
                f"alors qu'il est censé déjà exister. Abandon plutôt que de "
                f"repartir de zéro et risquer d'écraser le vrai fichier.")
        print(f"  [drive] {name} absent sur Drive (premier run) — normal, on continue à vide.")
        return False
    request = service.files().get_media(fileId=file_id)
    with open(local_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    print(f"  [drive] {name} téléchargé.")
    return True


def upload(name, local_path):
    """Téléverse `local_path` vers Drive sous le nom `name` (crée ou
    remplace). Ne fait rien (silencieux, pas d'erreur) si le fichier local
    est absent — cas normal pour un cache jamais généré ce run. Toute autre
    erreur (auth, réseau, quota) lève une exception : un échec d'envoi ne
    doit jamais passer pour un succès dans le mail de notification."""
    if not os.path.exists(local_path):
        print(f"  [drive] {local_path} absent localement — rien à envoyer pour {name}.")
        return
    service = _service()
    file_id = _find_file_id(service, name)
    media = MediaIoBaseUpload(io.FileIO(local_path, "rb"),
                               mimetype="application/octet-stream", resumable=True)
    if file_id:
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        meta = {"name": name, "parents": [_folder_id()]}
        service.files().create(body=meta, media_body=media).execute()
    print(f"  [drive] {name} envoyé.")
