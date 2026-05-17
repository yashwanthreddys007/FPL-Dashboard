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
        "selected_by_percent", "position_rank"
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
    current_gw = get_current_gw()

if df.empty:
    st.error("Could not load data.")
    st.stop()

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

top_n = st.sidebar.slider("Show top N players", 10, 822, 100)

# --- APPLY FILTERS ---
filtered = df.copy()

if position != "All":
    filtered = filtered[filtered["position_name"] == position]

filtered = filtered[filtered["price_m"] <= max_price]

if form_filter:
    filtered = filtered[
        (filtered["form_tier"].isin(form_filter)) | (filtered["form_tier"].isna())
    ]

if value_only:
    filtered = filtered[filtered["is_value_pick"] == "true"]

filtered = filtered.sort_values("fpl_score", ascending=False).head(top_n)

# --- METRICS ROW ---
c1, c2, c3, c4 = st.columns(4)
c1.metric("Players shown", len(filtered))
c2.metric("Avg FPL score", f"{filtered['fpl_score'].mean():.2f}" if len(filtered) > 0 else "—")
c3.metric("Avg price", f"£{filtered['price_m'].mean():.1f}m" if len(filtered) > 0 else "—")
c4.metric("Value picks", (filtered["is_value_pick"] == "true").sum())

st.divider()

# --- MAIN TABLE ---
if len(filtered) == 0:
    st.warning("No players match your filters. Try adjusting them.")
else:
    display_df = filtered[[
        "position_name",
        "player_name",
        "plays_for",
        "price_m",
        "fpl_form",
        "form_tier",
        "fpl_score",
        "next_5_fixtures",
        "availability_status",
        "is_value_pick",
        "total_points",
        "goals_scored",
        "assists",
        "clean_sheets",
        "selected_by_percent"
    ]].rename(columns={
        "position_name":       "Pos",
        "player_name":         "Player",
        "plays_for":           "Team",
        "price_m":             "Price",
        "fpl_form":            "Form",
        "form_tier":           "Tier",
        "fpl_score":           "FPL Score",
        "next_5_fixtures":     "Next 5 fixtures",
        "availability_status": "Status",
        "is_value_pick":       "Value?",
        "total_points":        "Pts",
        "goals_scored":        "G",
        "assists":             "A",
        "clean_sheets":        "CS",
        "selected_by_percent": "Ownership%"
    }).copy()

    display_df["Price"]      = display_df["Price"].map(lambda x: f"£{float(x):.1f}m")
    display_df["Form"]       = display_df["Form"].map(lambda x: f"{float(x):.1f}")
    display_df["FPL Score"]  = display_df["FPL Score"].map(lambda x: f"{float(x):.2f}")
    display_df["Ownership%"] = display_df["Ownership%"].map(lambda x: f"{float(x):.1f}%")

    st.dataframe(
        display_df,
        use_container_width=True,
        height=500
    )

    # --- PLAYER DETAIL ---
    st.divider()
    st.subheader("Player detail")

    selected_player = st.selectbox(
        "Select a player for more detail",
        filtered["player_name"].tolist()
    )

    row = filtered[filtered["player_name"] == selected_player].iloc[0]

    d1, d2, d3, d4, d5 = st.columns(5)
    d1.metric("FPL Score", f"{row['fpl_score']:.2f}")
    d2.metric("Form",      f"{row['fpl_form']:.1f}")
    d3.metric("Price",     f"£{row['price_m']:.1f}m")
    d4.metric("Total pts", int(row["total_points"]))
    d5.metric("Ownership", f"{row['selected_by_percent']:.1f}%")

    st.markdown(f"**Next 5 fixtures:** {row['next_5_fixtures']}")

    col1, col2, col3 = st.columns(3)
    col1.metric("Goals",        int(row["goals_scored"]))
    col2.metric("Assists",      int(row["assists"]))
    col3.metric("Clean sheets", int(row["clean_sheets"]))


st.divider()
st.caption("Data: FPL Official API · Pipeline: PySpark + Databricks + dbt · Built by Yashwanth Reddy")
