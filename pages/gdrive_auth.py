# pages/gdrive_auth.py
# ====================
# One-time Google Drive OAuth setup page.
#
# Flow:
#   1. User pastes their OAuth Client ID + Secret (from Google Cloud Console).
#   2. App generates an authorization URL.
#   3. User visits the URL, grants permission, copies the auth code.
#   4. App exchanges the code for tokens and displays the refresh_token.
#   5. User copies the three values into Streamlit Secrets → Drive is permanently connected.

import json
import streamlit as st
from google_auth_oauthlib.flow import Flow
from gdrive_store import load_credentials_from_secrets, GDriveStore

SCOPES = ["https://www.googleapis.com/auth/drive"]
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"  # "copy the code" flow — works without a redirect server


def _check_secrets_connection() -> bool:
    """Return True if valid credentials are already in Streamlit Secrets."""
    try:
        creds = load_credentials_from_secrets()
        return creds is not None and creds.valid
    except Exception:
        return False


def render():
    st.title("Google Drive — Persistent Storage Setup")

    # ── Already connected via Secrets ───────────────────────────────────────
    if _check_secrets_connection():
        st.success("✅ Google Drive is connected and working via Streamlit Secrets.")
        st.markdown(
            "Files are automatically saved to your Google Drive folder "
            "**Brovarski_Papers_App** and will persist across all app restarts."
        )
        try:
            store = GDriveStore()
            uploads = store.list_files(store.uploads_id)
            trans   = store.list_files(store.transcriptions_id)
            col1, col2 = st.columns(2)
            col1.metric("Images in Drive", len(uploads))
            col2.metric("Transcriptions in Drive", len(trans))
        except Exception as e:
            st.warning(f"Could not read Drive folder counts: {e}")
        return

    # ── Session-state connection (credentials entered this session) ──────────
    if st.session_state.get("gdrive_creds"):
        st.success("✅ Google Drive connected for this session.")
        st.info(
            "To make this **permanent** (survive app restarts), copy the values below "
            "into your Streamlit Secrets. See Step 3 in the instructions."
        )
        try:
            creds_dict = json.loads(st.session_state["gdrive_creds"])
            st.code(
                f"""[gdrive]
client_id     = "{creds_dict.get('client_id', '')}"
client_secret = "{creds_dict.get('client_secret', '')}"
refresh_token = "{creds_dict.get('refresh_token', '')}"
token_uri     = "https://oauth2.googleapis.com/token"
""",
                language="toml",
            )
            st.markdown(
                "**How to save this permanently:**\n"
                "1. Go to [share.streamlit.io](https://share.streamlit.io) → your app → ⋮ menu → **Settings → Secrets**\n"
                "2. Paste the block above into the Secrets editor\n"
                "3. Click **Save** — the app will restart and Drive will be permanently connected"
            )
        except Exception:
            pass

        if st.button("Disconnect"):
            del st.session_state["gdrive_creds"]
            st.rerun()
        return

    # ── Setup instructions ───────────────────────────────────────────────────
    st.markdown(
        """
This is a **one-time setup** that takes about 5 minutes. After completing it, 
Google Drive will be permanently connected — no login required ever again.

---

### Step 1 — Create an OAuth App in Google Cloud Console

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. In the left menu go to **APIs & Services → Library**
4. Search for **Google Drive API** and click **Enable**
5. Go to **APIs & Services → OAuth consent screen**
   - Choose **External**, click Create
   - Fill in App name (e.g. `Brovarski Papers`), your email, and save
   - On the **Scopes** page click **Save and Continue** (no scopes needed here)
   - On the **Test users** page, add your own Google email address, then Save
6. Go to **APIs & Services → Credentials**
   - Click **+ Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Name it anything (e.g. `Brovarski App`)
   - Click **Create**
7. A dialog appears with your **Client ID** and **Client Secret** — copy both

---

### Step 2 — Enter Your Client ID and Secret Below
        """
    )

    with st.form("oauth_form"):
        client_id     = st.text_input("Client ID",     placeholder="xxxx.apps.googleusercontent.com")
        client_secret = st.text_input("Client Secret", placeholder="GOCSPX-...", type="password")
        submitted = st.form_submit_button("Generate Authorization URL", type="primary")

    if submitted and client_id and client_secret:
        st.session_state["_gdrive_client_id"]     = client_id
        st.session_state["_gdrive_client_secret"] = client_secret

    client_id     = st.session_state.get("_gdrive_client_id", "")
    client_secret = st.session_state.get("_gdrive_client_secret", "")

    if client_id and client_secret:
        client_config = {
            "installed": {
                "client_id":     client_id,
                "client_secret": client_secret,
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI],
            }
        }
        try:
            flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)
            auth_url, _ = flow.authorization_url(
                prompt="consent",
                access_type="offline",   # ensures we get a refresh_token
            )

            st.divider()
            st.markdown("### Step 3 — Authorize Access")
            st.markdown(
                "Click the link below. Sign in with your Google account, grant permission, "
                "then copy the **authorization code** Google gives you."
            )
            st.markdown(f"**[→ Click here to authorize Google Drive access]({auth_url})**")
            st.divider()

            st.markdown("### Step 4 — Paste the Authorization Code")
            auth_code = st.text_input("Paste the authorization code here", key="auth_code_input")

            if st.button("Connect Google Drive", type="primary", disabled=not auth_code):
                with st.spinner("Exchanging code for tokens…"):
                    try:
                        flow.fetch_token(code=auth_code.strip())
                        creds = flow.credentials
                        creds_dict = {
                            "token":         creds.token,
                            "refresh_token": creds.refresh_token,
                            "token_uri":     creds.token_uri,
                            "client_id":     creds.client_id,
                            "client_secret": creds.client_secret,
                        }
                        st.session_state["gdrive_creds"] = json.dumps(creds_dict)
                        st.success("✅ Connected! Scroll up to see your Secrets snippet.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to exchange code: {e}")
                        st.info("Make sure you copied the full code and that it hasn't expired (codes expire in ~10 minutes).")
        except Exception as e:
            st.error(f"Could not build OAuth flow: {e}")
