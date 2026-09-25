"""
get_refresh_token.py
Ise apne PC/laptop par SIRF EK BAAR chalao (GitHub Actions me nahi).
Isi folder me 'client_secret.json' honi chahiye (Google Cloud Console
se download ki hui OAuth Desktop app credentials file).

Install karo pehle: pip install google-auth-oauthlib
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/drive",
]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0)

print("\n=== Ye REFRESH TOKEN copy karke GitHub Secrets me REFRESH_TOKEN naam se daalo ===\n")
print(creds.refresh_token)
print("\n===============================================================================\n")
