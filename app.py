import streamlit as st
import pandas as pd
import requests
import time

st.set_page_config(
    page_title="FPL Player Recommender",
    page_icon="⚽",
    layout="wide"
)

@st.cache_resource
def get_oauth_token():
    host = st.secrets["DATABRICKS_HOST"]
    client_id = st.secrets["DATABRICKS_CLIENT_ID"]
    client_secret = st.secrets["DATABRICKS_CLIENT_SECRET"]

    token_url = f"https://{host}/oidc/v1/token"
    response = requests.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "scope": "sql all-apis",
            "client_id": client_id,
            "client_secret": client_secret
        }
    )

    if response.status_code != 200:
        st.error(f"OAuth error: {response.text}")
        return None

    return response.json()["access_token"]


@st.cache_data(ttl=3600)
def get_current_gw():
    try:
        r = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/")
        events = r.json()["events"]
        current = next((e for e in events if e["is_current"]), None)
        if current:
            return current["id"]
        next_gw = next((e for e in events if e["is_next"]), None)
        return next_gw["id"] if next_gw else "current"
    except:
        return "current"


@st.cache_data(ttl=3600)
def load_recommendations():
    host = st.secrets["DATABRICKS_HOST"]
    http_path = st.secrets["DATABRICKS_HTTP_PATH"]
    warehouse_id = http_path.split("/")[-1]
    token = get_oauth_token()

    if not token:
        return pd.DataFr
