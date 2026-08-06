# -*- coding: utf-8 -*-
"""Synchronisation des fichiers d'état (Excel de travail + caches JSON) avec
un dossier Google Drive.

Pourquoi : le pipeline tourne depuis GitHub Actions (machine éphémère, sans
accès au PC local), mais le fichier Excel est édité manuellement en local
(surlignages, lignes supprimées, notes). Google Drive sert de source de
vérité commune : ce module télécharge l'état avant le run, la logique de
fusion existante (`update_excel`, jamais destructive) fait le reste, puis on
renvoie l'état mis à jour vers Drive.

Authentification : compte de service (JSON dans la variable d'env
GDRIVE_SA_KEY_JSON), dossier cible via GDRIVE_FOLDER_ID. Le compte de
service doit avoir un accès "Éditeur" sur ce dossier (partagé manuellement
depuis Drive, cf. README).

Ne plante jamais sur un fichier absent (premier run) : le pipeline sait
démarrer sur des caches vides (comportement déjà en place partout ailleurs).
"""
import io
import json
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]

_SERVICE = None  # mise en cache : un seul client par process


def _service():
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    key_json = os.environ.get("GDRIVE_SA_KEY_JSON")
    if not key_json:
        raise RuntimeError("GDRIVE_SA_KEY_JSON non définie")
    info = json.loads(key_json)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    _SERVICE = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _SERVICE


def _folder_id():
    fid = os.environ.get("GDRIVE_FOLDER_ID")
    if not fid:
        raise RuntimeError("GDRIVE_FOLDER_ID non définie")
    return fid


def _find_file_id(service, name):
    q = f"'{_folder_id()}' in parents and name = '{name}' and trashed = false"
    res = service.files().list(q=q, fields="files(id, name)", pageSize=1).execute()
    fichiers = res.get("files", [])
    return fichiers[0]["id"] if fichiers else None


def download(name, local_path):
    """Télécharge `name` depuis le dossier Drive vers `local_path`.
    Renvoie False (sans lever d'exception) si le fichier n'existe pas encore
    sur Drive — cas normal au tout premier run."""
    try:
        service = _service()
        file_id = _find_file_id(service, name)
    except Exception as e:
        print(f"  [drive] téléchargement de {name} impossible ({e}) — ignoré.")
        return False
    if not file_id:
        print(f"  [drive] {name} absent sur Drive (premier run ?) — ignoré.")
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
    remplace). N'échoue pas bruyamment si le fichier local est absent (ex :
    cache jamais généré ce run) — juste un message, jamais de crash."""
    if not os.path.exists(local_path):
        print(f"  [drive] {local_path} absent localement — rien à envoyer pour {name}.")
        return
    try:
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
    except Exception as e:
        print(f"  [drive] ERREUR envoi de {name} : {e}")
