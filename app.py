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
def load_recommendations():
    host = st.secrets["DATABRICKS_HOST"]
    http_path = st.secrets["DATABRICKS_HTTP_PATH"]
    warehouse_id = http_path.split("/")[-1]
    token = get_oauth_token()

    if not token:
        return pd.DataFrame()

    url = f"https://{host}/api/2.0/sql/statements"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "statement": """
            SELECT
                position_name,
                position_rank,
                player_name,
                plays_for,
                price_m,
                fpl_form,
                form_tier,
                next_5_fixtures,
                gw1_num,
                fixture_score,
                availability_status,
                fpl_score,
                is_value_pick,
                total_points,
                goals_scored,
                assists,
                clean_sheets,
                selected_by_percent
            FROM workspace.dbt_ysankepally_fpl_transformed.fpl_recommendations
            ORDER BY fpl_score DESC
        """,
        "warehouse_id": warehouse_id,
        "catalog": "workspace",
        "schema": "dbt_ysankepally_fpl_transformed",
        "wait_timeout": "30s",
        "disposition": "INLINE",
        "format": "JSON_ARRAY"
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        st.error(f"Query error: {response.status_code} — {response.text}")
        return pd.DataFrame()

    result = response.json()

    while result.get("status", {}).get("state") in ["PENDING", "RUNNING"]:
        time.sleep(2)
        statement_id = result["statement_id"]
        poll_url = f"https://{host}/api/2.0/sql/statements/{statement_id}"
        response = requests.get(poll_url, headers=headers)
        result = response.json()

    if result.get("status", {}).get("state") != "SUCCEEDED":
        st.error(f"Query failed: {result}")
        return pd.DataFrame()

    columns = [col["name"] for col in result["manifest"]["schema"]["columns"]]
    rows = result["result"]["data_array"]
    df = pd.DataFrame(rows, columns=columns)

    numeric_cols = [
        "price_m", "fpl_form", "fpl_score", "fixture_score",
        "total_points", "goals_scored", "assists", "clean_sheets",
        "selected_by_percent", "gw1_num", "position_rank"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


# --- HEADER ---
st.title("⚽ FPL Player Recommender")
st.markdown("Fantasy Premier League transfer recommendations based on form, fixtures and availability.")

# --- LOAD DATA ---
with st.spinner("Loading FPL data from Databricks..."):
    df = load_recommendations()

if df.empty:
    st.error("Could not load data.")
    st.stop()

# --- DYNAMIC CURRENT GW ---
current_gw = int(df["gw1_num"].dropna().iloc[0]) if not df["gw1_num"].dropna().empty else "current"
st.info(f"Showing recommendations from **GW{current_gw}** onwards — updated every hour.")

# --- SIDEBAR FILTERS ---
st.sidebar.header("Filters")

position = st.sidebar.selectbox(
    "Position",
    ["All", "GKP", "DEF", "MID", "FWD"]
)

max_price = st.sidebar.slider(
    "Max price (£m)",
    min_value=4.0,
    max_value=15.0,
    value=10.0,
    step=0.5
)

form_filter = st.sidebar.multiselect(
    "Form tier",
    ["elite", "good", "average", "poor"],
    default=["elite", "good"]
)

value_only = st.sidebar.checkbox("Value picks only", value=False)
