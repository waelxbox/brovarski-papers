# pages/gdrive_auth.py

import streamlit as st
from google_auth_oauthlib.flow import Flow
import json

CLIENT_SECRETS_JSON = """ 
{"installed":{"client_id":"YOUR_CLIENT_ID","project_id":"your-project-id","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_secret":"YOUR_CLIENT_SECRET","redirect_uris":["urn:ietf:wg:oauth:2.0:oob","http://localhost"]}}
"""

SCOPES = ["https://www.googleapis.com/auth/drive"]

def render():
    st.title("Connect to Google Drive")
    st.caption("To enable persistent storage, this app needs permission to access its own folder in your Google Drive.")

    if "gdrive_creds" in st.session_state:
        st.success("Google Drive is connected!")
        st.json(json.loads(st.session_state["gdrive_creds"]))
        if st.button("Disconnect Google Drive"):
            del st.session_state["gdrive_creds"]
            st.rerun()
        return

    st.info("You will be asked to grant permission for the app to access files and folders it creates in your Google Drive. The app cannot access any other files.")

    flow = Flow.from_client_secrets_info(
        json.loads(CLIENT_SECRETS_JSON),
        scopes=SCOPES,
        redirect_uri="urn:ietf:wg:oauth:2.0:oob"
    )

    auth_url, _ = flow.authorization_url(prompt="consent")

    st.markdown(f"[Click here to authorize access]({auth_url})", unsafe_allow_html=True)
    st.markdown("After authorizing, copy the code from Google and paste it below.")

    auth_code = st.text_input("Enter authorization code")

    if st.button("Connect"):
        if not auth_code:
            st.error("Please enter the authorization code.")
            return
        try:
            flow.fetch_token(code=auth_code)
            creds_json = flow.credentials.to_json()
            st.session_state["gdrive_creds"] = creds_json
            st.success("Successfully connected to Google Drive!")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to connect: {e}")
