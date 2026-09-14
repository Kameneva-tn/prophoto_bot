# -*- coding: utf-8 -*-
"""Завантаження замовлення в Google Drive через сервісний акаунт (без браузерного входу).
Налаштування (один раз):
 1. console.cloud.google.com → проєкт → увімкнути Google Drive API
 2. IAM & Admin → Service Accounts → Create → Keys → Add key (JSON) → зберегти як service_account.json поруч
 3. У Google Drive створити папку «ЗАМОВЛЕННЯ» і поділитись нею з e-mail сервісного акаунта (роль Editor)
 4. У .env: GOOGLE_SA_JSON=service_account.json  DRIVE_ORDERS_FOLDER_ID=<id папки з адресного рядка>
"""
import os, glob, mimetypes
HERE = os.path.dirname(os.path.abspath(__file__))

TOKEN = os.path.join(HERE, "token.json")          # OAuth-варіант: python3 drive_sa.py auth
SCOPES = ["https://www.googleapis.com/auth/drive"]

def _sa_path():
    p = os.getenv("GOOGLE_SA_JSON"); return os.path.join(HERE, p) if p else None

def enabled():
    f = os.getenv("DRIVE_ORDERS_FOLDER_ID")
    sa = _sa_path()
    return bool(f) and ((sa and os.path.exists(sa)) or os.path.exists(TOKEN))

def _creds():
    sa = _sa_path()
    if sa and os.path.exists(sa):
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(sa, scopes=SCOPES)
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request()); open(TOKEN, "w").write(creds.to_json())
    return creds

def _svc():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_creds())

def auth():
    """Одноразовий вхід у Google через браузер (потрібен credentials.json — OAuth-клієнт типу Desktop)."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    cred = os.path.join(HERE, "credentials.json")
    if not os.path.exists(cred): raise SystemExit("Немає credentials.json (Google Cloud → APIs & Services → Credentials → OAuth client ID → Desktop app → Download JSON)")
    creds = InstalledAppFlow.from_client_secrets_file(cred, SCOPES).run_local_server(port=0)
    open(TOKEN, "w").write(creds.to_json()); print("Токен збережено у token.json")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "auth": auth()
    elif len(sys.argv) > 1 and sys.argv[1] == "test":
        svc = _svc(); print(svc.files().get(fileId=os.getenv("DRIVE_ORDERS_FOLDER_ID"), fields="name", supportsAllDrives=True).execute())
    else: print(__doc__)

def upload_order(order_dir, order_id):
    from googleapiclient.http import MediaFileUpload
    svc = _svc(); parent = os.getenv("DRIVE_ORDERS_FOLDER_ID")
    folder = svc.files().create(body={"name": order_id, "mimeType": "application/vnd.google-apps.folder", "parents": [parent]},
                                fields="id,webViewLink", supportsAllDrives=True).execute()
    # доступ успадковується від вашої папки ЗАМОВЛЕННЯ — публічного лінка не створюємо
    files = glob.glob(os.path.join(order_dir, "*")) + glob.glob(os.path.join(order_dir, "photos", "*"))
    for f in files:
        if os.path.isdir(f): continue
        mime = mimetypes.guess_type(f)[0] or "application/octet-stream"
        svc.files().create(body={"name": os.path.basename(f), "parents": [folder["id"]]},
                           media_body=MediaFileUpload(f, mimetype=mime, resumable=True), fields="id", supportsAllDrives=True).execute()
    return folder["webViewLink"]


# ----------------------------------------------------------------------------- доставка готових макетів
# Папка «ГОТОВО» (DRIVE_DELIVERY_FOLDER_ID): усе, що туди потрапляє, бот надсилає в чат і переносить у підпапку «ВІДПРАВЛЕНО».
# Підпис до файлу: якщо назва файлу містить " -- текст.jpg", частина після " -- " іде підписом.
def delivery_enabled():
    return enabled() and bool(os.getenv("DRIVE_DELIVERY_FOLDER_ID"))

def _sent_folder(svc, parent):
    q = f"'{parent}' in parents and mimeType='application/vnd.google-apps.folder' and name='ВІДПРАВЛЕНО' and trashed=false"
    r = svc.files().list(q=q, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files", [])
    if r: return r[0]["id"]
    return svc.files().create(body={"name": "ВІДПРАВЛЕНО", "mimeType": "application/vnd.google-apps.folder", "parents": [parent]},
                              fields="id", supportsAllDrives=True).execute()["id"]

def list_ready():
    """Нові файли в «ГОТОВО» (без папок)."""
    svc = _svc(); parent = os.getenv("DRIVE_DELIVERY_FOLDER_ID")
    q = f"'{parent}' in parents and mimeType!='application/vnd.google-apps.folder' and trashed=false"
    return svc.files().list(q=q, fields="files(id,name,mimeType,size)", orderBy="createdTime",
                            supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files", [])

def download(file_id, dest):
    from googleapiclient.http import MediaIoBaseDownload
    svc = _svc(); req = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
    with open(dest, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req); done = False
        while not done: _, done = dl.next_chunk()
    return dest

def mark_sent(file_id):
    svc = _svc(); parent = os.getenv("DRIVE_DELIVERY_FOLDER_ID"); dest = _sent_folder(svc, parent)
    svc.files().update(fileId=file_id, addParents=dest, removeParents=parent, fields="id", supportsAllDrives=True).execute()
