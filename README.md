# YouTube Shorts Auto-Uploader (Drive → YouTube via GitHub Actions)

## Files
- `drive_to_youtube.py` — main bot: Drive se video uthata hai, YouTube pe upload karta hai
- `get_refresh_token.py` — sirf ek baar apne PC pe chalane wali script (refresh token nikalne ke liye)
- `requirements.txt` — Python dependencies
- `.github/workflows/upload.yml` — GitHub Actions cron (roz 8 PM IST)

## Setup (ek baar)
1. Google Cloud Console me project banao, **YouTube Data API v3** aur **Google Drive API** enable karo.
2. OAuth consent screen banao, scopes add karo (`youtube.upload`, `drive`), publishing status **"In production"** karo.
3. OAuth Client ID banao — type **Desktop app** — `client_secret.json` download karo.
4. `get_refresh_token.py` apne PC pe chalao, login karke **REFRESH_TOKEN** copy karo.
5. Google Drive me videos wala folder banao, uski **Folder ID** URL se copy karo.
6. GitHub repo Settings → Secrets and variables → Actions me add karo:
   - `CLIENT_ID`, `CLIENT_SECRET`, `REFRESH_TOKEN`, `DRIVE_FOLDER_ID`, (optional) `UPLOADED_FOLDER_ID`
7. Repo me code push karo — cron automatically roz 8 PM IST chalega.

## Test karne ke liye
GitHub repo → **Actions** tab → workflow select karo → **Run workflow** (manual trigger), taaki cron ka wait kiye bina turant test ho jaaye.

## Yaad rakhne wali baatein
- YouTube API ka daily quota 10,000 units hai; ek upload ~1600 units leta hai (~6 uploads/din max).
- Video ko YouTube "Shorts" me count karne ke liye video vertical aur ≤60 seconds honi chahiye, aur title/description me `#shorts` hona chahiye.
- GitHub Actions ka scheduled cron kabhi-kabhi 5-15 min late chal sakta hai — ye GitHub ki taraf se hai, isme fix karne ka koi tarika nahi.
