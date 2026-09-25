"""
drive_to_youtube.py
Google Drive ke ek folder se sabse purani pending video uthaकर
YouTube par upload karta hai. GitHub Actions (daily cron) ke
through chalane ke liye banaya gaya hai.
"""

import os
import io
import json
import time

import google.generativeai as genai
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# ---------- Secrets / Config (GitHub Actions "Secrets" se aayenge) ----------
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["REFRESH_TOKEN"]
DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]             # jahan se videos uthani hain
UPLOADED_FOLDER_ID = os.environ.get("UPLOADED_FOLDER_ID")   # optional: upload hone ke baad yahan move
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")            # AI se title/hashtags banwane ke liye

PRIVACY_STATUS = "public"   # "public" / "unlisted" / "private" me se koi ek

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/drive",
]


def get_credentials():
    creds = Credentials(
        token=None,
        refresh_token=REFRESH_TOKEN,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def get_next_video(drive):
    """DRIVE_FOLDER_ID me sabse purani pending video file dhoondo."""
    query = f"'{DRIVE_FOLDER_ID}' in parents and mimeType contains 'video/' and trashed = false"
    result = drive.files().list(
        q=query,
        orderBy="createdTime",
        fields="files(id, name, parents)",
        pageSize=5,
    ).execute()
    files = result.get("files", [])
    return files[0] if files else None


def download_file(drive, file_id, file_name):
    local_path = f"/tmp/{file_name}"
    request = drive.files().get_media(fileId=file_id)
    with io.FileIO(local_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            pct = int(status.progress() * 100) if status else 0
            print(f"Download: {pct}%")
    return local_path


def generate_title_and_hashtags(video_path):
    """
    Gemini AI ko video bhejo, wo dekh kar catchy title, description
    aur hashtags bana kar deta hai. Agar GEMINI_API_KEY nahi hai ya
    kuch error aaya, to None return hota hai (filename fallback use hoga).
    """
    if not GEMINI_API_KEY:
        return None

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        video_file = genai.upload_file(path=video_path)

        # Gemini file ko process karne me kuch second lagte hain
        while video_file.state.name == "PROCESSING":
            time.sleep(3)
            video_file = genai.get_file(video_file.name)

        model = genai.GenerativeModel("gemini-3.5-flash")
        prompt = (
            "Ye ek YouTube Short video hai. Poora video dekho aur ek "
            "catchy, click-worthy YouTube title (max 90 characters), "
            "ek 1-2 line description, aur reach/discovery ke liye 8-10 "
            "relevant trending hashtags suggest karo (video ke content, "
            "niche aur general viral tags dono mix karke, jaise #shorts "
            "#viral #trending ke saath content-specific tags). SIRF is "
            'JSON format me jawab do, kuch aur text mat likho: '
            '{"title": "...", "description": "...", '
            '"hashtags": ["#tag1", "#tag2", "..."]}'
        )
        response = model.generate_content([video_file, prompt])
        text = response.text.strip()
        text = text.strip("`").replace("json", "", 1).strip()
        return json.loads(text)
    except Exception as e:
        print(f"AI title generation fail hui, filename use kar rahe hain: {e}")
        return None


def safe_title(raw_title: str) -> str:
    """YouTube title max 100 chars ki hoti hai aur khaali nahi ho sakti."""
    cleaned = (raw_title or "").replace("<", "").replace(">", "").strip()
    if not cleaned:
        cleaned = "Short Video"
    if len(cleaned) > 100:
        cleaned = cleaned[:97].strip() + "..."
    return cleaned


def upload_to_youtube(youtube, video_path, title, description, tags):
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload: {int(status.progress() * 100)}%")
    print(f"Uploaded! Video ID: {response['id']}")


def mark_as_done(drive, file_id, previous_parents):
    """Upload ke baad file ko 'Uploaded' folder me move kar do, warna delete kar do."""
    if UPLOADED_FOLDER_ID:
        drive.files().update(
            fileId=file_id,
            addParents=UPLOADED_FOLDER_ID,
            removeParents=previous_parents,
            fields="id, parents",
        ).execute()
    else:
        drive.files().delete(fileId=file_id).execute()


def main():
    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    youtube = build("youtube", "v3", credentials=creds)

    video = get_next_video(drive)
    if not video:
        print("Folder me koi nayi video nahi mili, aaj skip ho gaya.")
        return

    print(f"Processing: {video['name']}")
    local_path = download_file(drive, video["id"], video["name"])

    ai_result = generate_title_and_hashtags(local_path)
    if ai_result:
        hashtags = ai_result.get("hashtags", ["#shorts"])
        title = safe_title(ai_result.get("title", ""))
        description = ai_result.get("description", "") + "\n\n" + " ".join(hashtags)
        tags = list({h.lstrip("#").strip() for h in hashtags if h.strip("#").strip()})
        print(f"AI title: {title}")
    else:
        title = safe_title(os.path.splitext(video["name"])[0] + " #shorts")
        default_hashtags = ["#shorts", "#viral", "#trending", "#reels", "#fyp", "#shortvideo"]
        description = "Automatically uploaded via GitHub Actions bot.\n\n" + " ".join(default_hashtags)
        tags = [h.lstrip("#") for h in default_hashtags]

    upload_to_youtube(youtube, local_path, title, description, tags)
    mark_as_done(drive, video["id"], ",".join(video.get("parents", [])))
    os.remove(local_path)


if __name__ == "__main__":
    main()
