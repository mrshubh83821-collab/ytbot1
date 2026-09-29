"""
drive_to_youtube.py
Google Drive ke ek folder se sabse purani pending video uthaकर
YouTube par upload karta hai. GitHub Actions (daily cron) ke
through chalane ke liye banaya gaya hai.
"""

import os
import io
import json
import subprocess

from groq import Groq
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
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")                # AI se title/hashtags banwane ke liye (free, Groq)

PRIVACY_STATUS = "public"   # "public" / "unlisted" / "private" me se koi ek

# Ye tags HAMESHA lagenge, AI kuch bhi bole - reach/discovery badhane ke liye.
BASE_TAGS = [
    "shorts", "viral", "trending", "reels", "fyp", "foryou", "foryoupage",
    "viralvideo", "shortsvideo", "trendingvideo", "explorepage", "instareels",
    "reelsvideo", "viralreels", "shortsfeed", "youtubeshorts", "shortsyoutube",
    "viralshorts", "explore", "trending2026",
]


def combine_tags(extra_hashtags):
    """
    AI (ya kuch bhi) se mile hashtags + hamesha wale BASE_TAGS ko milakar
    ek duplicate-free list banao. YouTube tags field ki ~500 character
    limit ka bhi khayal rakhte hain.
    """
    cleaned_extra = [h.lstrip("#").strip() for h in extra_hashtags if h.strip("#").strip()]
    combined, seen = [], set()
    for tag in cleaned_extra + BASE_TAGS:
        key = tag.lower()
        if key and key not in seen:
            seen.add(key)
            combined.append(tag)

    final_tags, total_len = [], 0
    for tag in combined:
        total_len += len(tag) + 1
        if total_len > 480:
            break
        final_tags.append(tag)
    return final_tags

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
    # Drive file names kabhi-kabhi bahut lambe (poori caption jaisi) hote hain,
    # jo local filesystem par crash kar sakte hain. Isliye local file ka naam
    # hamesha safe file_id + extension se banate hain, original naam se nahi.
    ext = os.path.splitext(file_name)[1] or ".mp4"
    local_path = f"/tmp/{file_id}{ext}"
    request = drive.files().get_media(fileId=file_id)
    with io.FileIO(local_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            pct = int(status.progress() * 100) if status else 0
            print(f"Download: {pct}%")
    return local_path


def extract_audio(video_path):
    """ffmpeg se video ka audio nikal kar mp3 banao (Whisper ke liye)."""
    audio_path = video_path.rsplit(".", 1)[0] + ".mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "libmp3lame", audio_path],
        check=True, capture_output=True,
    )
    return audio_path


def generate_title_and_hashtags(video_path):
    """
    Groq (free, no card) se video ka title/hashtags banwao:
    1) Video ka audio nikal kar Whisper se "sunkar" text banao
    2) Us text (ya khaali ho to sirf filename) ke basis pe Llama se
       catchy title + description + hashtags likhwao
    Agar GROQ_API_KEY nahi hai ya kuch error aaya, None return hota
    hai (filename fallback use hoga).
    """
    if not GROQ_API_KEY:
        return None

    try:
        client = Groq(api_key=GROQ_API_KEY)

        transcript_text = ""
        try:
            audio_path = extract_audio(video_path)
            with open(audio_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=f, model="whisper-large-v3"
                )
            transcript_text = (transcription.text or "").strip()
            os.remove(audio_path)
        except Exception as e:
            print(f"Audio transcribe skip hua (shayad silent video hai): {e}")

        prompt = (
            "Ye ek YouTube Short video hai. Iska audio transcript (agar "
            f'available hai): "{transcript_text[:800]}"\n\n'
            "Isi info ke aadhar par (agar transcript khaali hai to bhi "
            "generic-par-catchy) ek click-worthy YouTube title (max 90 "
            "characters), ek 1-2 line description, aur reach/discovery "
            "ke liye 8-10 relevant hashtags do (content-specific + "
            "#shorts #viral #trending jaise general tags mix karke). "
            "SIRF is JSON format me jawab do, kuch aur text mat likho: "
            '{"title": "...", "description": "...", '
            '"hashtags": ["#tag1", "#tag2", "..."]}'
        )
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
        )
        text = completion.choices[0].message.content.strip()
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
        title = safe_title(ai_result.get("title", ""))
        tags = [f"#{t}" for t in combine_tags(ai_result.get("hashtags", []))]
        hashtag_line = " ".join(tags)
        description = (ai_result.get("description", "") + "\n\n" + hashtag_line).strip()
        print(f"AI title: {title}")
    else:
        title = safe_title(os.path.splitext(video["name"])[0] + " #shorts")
        tags = [f"#{t}" for t in combine_tags([])]
        hashtag_line = " ".join(tags)
        description = ("Automatically uploaded via GitHub Actions bot.\n\n" + hashtag_line).strip()

    upload_to_youtube(youtube, local_path, title, description, tags)
    mark_as_done(drive, video["id"], ",".join(video.get("parents", [])))
    os.remove(local_path)


if __name__ == "__main__":
    main()
