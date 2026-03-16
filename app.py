import streamlit as st
import pandas as pd
import requests

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
    
    # Get OAuth token using M2M flow
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
                position_name, position_rank, player_name, plays_for,
                price_m, fpl_form, form_tier,
                fixture_gw1, fixture_gw2, fixture_gw3, fixture_gw4, fixture_gw5,
                gw1_num, fixture_score, availability_status, fpl_score,
                is_value_pick, total_points, goals_scored, assists,
                clean_sheets, selected_by_percent
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
    
    # Poll if still running
    import time
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

# --- LOAD ---
with st.spinner("Loading FPL data from Databricks..."):
    df = load_recommendations()

if df.empty:
    st.error("Could not load data.")
    st.stop()

gw1 = int(df["gw1_num"].dropna().iloc[0]) if not df["gw1_num"].dropna().empty else 30
gw2, gw3, gw4, gw5 = gw1+1, gw1+2, gw1+3, gw1+4

# --- SIDEBAR ---
st.sidebar.header("Filters")
position = st.sidebar.selectbox("Position", ["All", "GKP", "DEF", "MID", "FWD"])
max_price = st.sidebar.slider("Max price (£m)", 4.0, 15.0, 10.0, 0.5)
form_filter = st.sidebar.multiselect(
    "Form tier",
    ["elite", "good", "average", "poor"],
    default=["elite", "good"]
)
value_only = st.sidebar.checkbox("Value picks only", value=False)
top_n = st.sidebar.slider("Show top N players", 10, 822, 100)

# --- FILTER ---
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

# --- METRICS ---
c1, c2, c3, c4 = st.columns(4)
c1.metric("Players shown", len(filtered))
c2.metric("Avg FPL score", f"{filtered['fpl_score'].mean():.2f}" if len(filtered) > 0 else "—")
c3.metric("Avg price", f"£{filtered['price_m'].mean():.1f}m" if len(filtered) > 0 else "—")
c4.metric("Value picks", (filtered["is_value_pick"] == "true").sum())

st.divider()

# --- TABLE ---
if len(filtered) == 0:
    st.warning("No players match your filters.")
else:
    display_df = filtered[[
        "position_name", "player_name", "plays_for", "price_m",
        "fpl_form", "form_tier", "fpl_score",
        "fixture_gw1", "fixture_gw2", "fixture_gw3",
        "fixture_gw4", "fixture_gw5",
        "availability_status", "is_value_pick",
        "total_points", "goals_scored", "assists",
        "clean_sheets", "selected_by_percent"
    ]].rename(columns={
        "position_name": "Pos",
        "player_name": "Player",
        "plays_for": "Team",
        "price_m": "Price",
        "fpl_form": "Form",
        "form_tier": "Tier",
        "fpl_score": "FPL Score",
        "fixture_gw1": f"GW{gw1}",
        "fixture_gw2": f"GW{gw2}",
        "fixture_gw3": f"GW{gw3}",
        "fixture_gw4": f"GW{gw4}",
        "fixture_gw5": f"GW{gw5}",
        "availability_status": "Status",
        "is_value_pick": "Value?",
        "total_points": "Pts",
        "goals_scored": "G",
        "assists": "A",
        "clean_sheets": "CS",
        "selected_by_percent": "Ownership%"
    })

    # Format columns
display_df["Price"] = display_df["Price"].map(lambda x: f"£{x:.1f}m")
display_df["Form"] = display_df["Form"].map(lambda x: f"{x:.1f}")
display_df["FPL Score"] = display_df["FPL Score"].map(lambda x: f"{x:.2f}")
display_df["Ownership%"] = display_df["Ownership%"].map(lambda x: f"{x:.1f}%")

st.dataframe(
    display_df,
    use_container_width=True,
    height=500
)

st.divider()
st.subheader("Player detail")
selected_player = st.selectbox("Select a player", filtered["player_name"].tolist())
row = filtered[filtered["player_name"] == selected_player].iloc[0]

d1, d2, d3, d4, d5 = st.columns(5)
d1.metric("FPL Score", f"{row['fpl_score']:.2f}")
d2.metric("Form", f"{row['fpl_form']:.1f}")
d3.metric("Price", f"£{row['price_m']:.1f}m")
d4.metric("Total pts", int(row["total_points"]))
d5.metric("Ownership", f"{row['selected_by_percent']:.1f}%")
st.markdown(f"**Next 5 fixtures:** {row['fixture_gw1']} → {row['fixture_gw2']} → {row['fixture_gw3']} → {row['fixture_gw4']} → {row['fixture_gw5']}")

st.divider()
st.caption("Data: FPL Official API · Pipeline: PySpark + Databricks + dbt · Built by Yashwanth Reddy")
