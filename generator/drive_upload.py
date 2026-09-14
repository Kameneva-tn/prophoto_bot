#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Завантаження готових слайдів у Google Drive.

Одноразове налаштування:
  1. https://console.cloud.google.com → створити проєкт → увімкнути "Google Drive API"
  2. APIs & Services → Credentials → Create OAuth client ID → Desktop app → Download JSON
  3. зберегти його як credentials.json поруч із цим файлом
  4. pip install google-api-python-client google-auth-oauthlib

Використання:
  python drive_upload.py ./out --folder 1ZAX3ag3joaKvTwf6D-LzHkqFDw9z9c_o --name "Зйомка на білому фоні"

Створює підпапку з назвою --name всередині --folder і кладе туди всі slide_*.jpg/png.
Перший запуск відкриє браузер для входу в Google; далі токен зберігається в token.json.
"""
import os, sys, glob, argparse
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
HERE = os.path.dirname(os.path.abspath(__file__))

def service():
    tok = os.path.join(HERE, "token.json"); cred = os.path.join(HERE, "credentials.json")
    creds = Credentials.from_authorized_user_file(tok, SCOPES) if os.path.exists(tok) else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file(cred, SCOPES).run_local_server(port=0)
        open(tok, "w").write(creds.to_json())
    return build("drive", "v3", credentials=creds)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir"); ap.add_argument("--folder", required=True, help="ID батьківської папки на Drive")
    ap.add_argument("--name", required=True, help="назва підпапки для цього поста")
    a = ap.parse_args()
    svc = service()
    sub = svc.files().create(body={"name": a.name, "mimeType": "application/vnd.google-apps.folder",
                                   "parents": [a.folder]}, fields="id,webViewLink").execute()
    files = sorted(glob.glob(os.path.join(a.out_dir, "slide_*.jpg")) + glob.glob(os.path.join(a.out_dir, "slide_*.png")))
    for f in files:
        mime = "image/jpeg" if f.endswith(".jpg") else "image/png"
        svc.files().create(body={"name": os.path.basename(f), "parents": [sub["id"]]},
                           media_body=MediaFileUpload(f, mimetype=mime, resumable=True), fields="id").execute()
        print("↑", os.path.basename(f))
    print("Готово:", sub["webViewLink"])

if __name__ == "__main__":
    main()
