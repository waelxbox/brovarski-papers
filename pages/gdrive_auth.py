import streamlit as st
from google_auth_oauthlib.flow import Flow
import json

SCOPES = ["https://www.googleapis.com/auth/drive"]

def render():
    st.title("🔗 Connect Google Drive")
    st.caption("Connect your personal Google account for permanent file storage.")

    # Already connected
    if "oauth_gdrive_creds" in st.session_state:
        st.success("✅ Google Drive is connected!")
        st.info("All uploads and transcriptions are being saved to your Google Drive under **Brovarski_Papers_App/**.")
        if st.button("Disconnect"):
            del st.session_state["oauth_gdrive_creds"]
            st.rerun()
        return

    if "OAUTH_CLIENT_SECRETS" not in st.secrets:
        st.error("⚠️ Missing `OAUTH_CLIENT_SECRETS` in Streamlit Secrets.")
        st.markdown("""
**To fix this**, go to your app's Streamlit Secrets and add:

```toml
OAUTH_CLIENT_SECRETS = '{"installed":{"client_id":"...","client_secret":"...","auth_uri":"...","token_uri":"...","redirect_uris":["urn:ietf:wg:oauth:2.0:oob"]}}'
```

Paste the full contents of your `client_secrets.json` file as a single-line JSON string.
        """)
        return

    try:
        # Build the OAuth flow once and store it in session state
        if "oauth_flow" not in st.session_state:
            client_secrets = json.loads(st.secrets["OAUTH_CLIENT_SECRETS"])
            flow = Flow.from_client_config(
                client_secrets,
                scopes=SCOPES,
                redirect_uri="urn:ietf:wg:oauth:2.0:oob"
            )
            auth_url, _ = flow.authorization_url(prompt="consent")

            st.session_state["oauth_flow"] = flow
            st.session_state["auth_url"] = auth_url

        st.markdown("### Step 1 — Authorize Access")
        st.markdown(
            f"**[→ Click here to authorize Google Drive access]({st.session_state['auth_url']})**",
            unsafe_allow_html=True
        )
        st.info("Sign in with your Google account and click **Allow**. Google will show you a short authorization code.")

        st.markdown("### Step 2 — Paste the Code")
        auth_code = st.text_input("Paste the authorization code from Google here:")

        if st.button("Connect Google Drive", type="primary", disabled=not auth_code):
            flow = st.session_state["oauth_flow"]
            flow.fetch_token(code=auth_code.strip())

            st.session_state["oauth_gdrive_creds"] = json.loads(flow.credentials.to_json())

            del st.session_state["oauth_flow"]
            del st.session_state["auth_url"]

            st.success("✅ Connected! Google Drive is now active.")
            st.rerun()

    except Exception as e:
        st.error(f"Authentication failed: {e}")
