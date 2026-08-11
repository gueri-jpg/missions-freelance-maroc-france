# -*- coding: utf-8 -*-
"""Script de diagnostic TEMPORAIRE — à supprimer une fois le problème d'accès
Drive résolu. Ne télécharge/n'envoie rien : vérifie juste si le compte de
service voit réellement le dossier ciblé par GDRIVE_FOLDER_ID, et liste ce
qu'il y trouve."""
import json
import os

import drive_sync as DRIVE

fid = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
key_json = os.environ.get("GDRIVE_SA_KEY_JSON", "").strip()

print(f"ID dossier reçu (longueur {len(fid)}) : {fid[:6]}...{fid[-6:]}")
print(f"Compte de service utilisé : {json.loads(key_json).get('client_email')}")

service = DRIVE._service()

try:
    meta = service.files().get(fileId=fid, fields="id,name,driveId").execute()
    print(f"OK — le compte de service VOIT ce dossier : {meta}")
except Exception as e:
    print(f"ÉCHEC get par ID — dossier invisible pour ce compte, ou ID incorrect : {e}")

try:
    res = service.files().list(
        q=f"'{fid}' in parents and trashed = false",
        fields="files(id, name)",
    ).execute()
    print(f"Fichiers visibles dans ce dossier par ce compte : {res.get('files')}")
except Exception as e:
    print(f"ÉCHEC listing du dossier : {e}")
