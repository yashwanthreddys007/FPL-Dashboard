import streamlit as st
import pandas as pd
from databricks import sql
import os

st.set_page_config(
    page_title="FPL Player Recommender",
    page_icon="⚽",
    layout="wide"
)

# --- CONNECTION ---
@st.cache_resource
def get_connection():
    return sql.connect(
        server_hostname=st.secrets["dbc-d9325b27-c4b2.cloud.databricks.com"],
        http_path=st.secrets["/sql/1.0/warehouses/a07915066f17cad8"],
        access_token=st.secrets["d816232a06df93fe921c001fbb583c"]
    )

@st.cache_data(ttl=3600)
def load_recommendations():
    conn = get_connection()
    query = """
        SELECT
            position_name,
            position_rank,
            player_name,
            plays_for,
            price_m,
            fpl_form,
            form_tier,
            fixture_gw1,
            fixture_gw2,
            fixture_gw3,
            fixture_gw4,
            fixture_gw5,
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
    """
    with conn.cursor() as cursor:
        cursor.execute(query)
        df = pd.DataFrame(
            cursor.fetchall(),
            columns=[d[0] for d in cursor.description]
        )
    return df

# --- HEADER ---
st.title("FPL Player Recommender")
st.markdown("AI-powered Fantasy Premier League transfer recommendations based on form, fixtures and availability.")

# --- LOAD DATA ---
with st.spinner("Loading FPL data..."):
    df = load_recommendations()

# Get current GW numbers for column labels
gw1 = int(df["gw1_num"].dropna().iloc[0]) if not df["gw1_num"].dropna().empty else "GW"
gw2, gw3, gw4, gw5 = gw1+1, gw1+2, gw1+3, gw1+4

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
top_n = st.sidebar.slider("Show top N players", 5, 50, 15)

# --- FILTER DATA ---
filtered = df.copy()

if position != "All":
    filtered = filtered[filtered["position_name"] == position]

filtered = filtered[filtered["price_m"] <= max_price]

if form_filter:
    filtered = filtered[filtered["form_tier"].isin(form_filter)]

if value_only:
    filtered = filtered[filtered["is_value_pick"] == True]

filtered = filtered.head(top_n)

# --- METRICS ROW ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Players shown", len(filtered))
col2.metric("Avg FPL score", f"{filtered['fpl_score'].mean():.2f}" if len(filtered) > 0 else "—")
col3.metric("Avg price", f"£{filtered['price_m'].mean():.1f}m" if len(filtered) > 0 else "—")
col4.metric("Value picks", filtered["is_value_pick"].sum())

st.divider()

# --- MAIN TABLE ---
if len(filtered) == 0:
    st.warning("No players match your filters. Try adjusting them.")
else:
    # Rename fixture columns to actual GW numbers
    display_df = filtered[[
        "position_name", "player_name", "plays_for", "price_m",
        "fpl_form", "form_tier", "fpl_score",
        "fixture_gw1", "fixture_gw2", "fixture_gw3",
        "fixture_gw4", "fixture_gw5",
        "availability_status", "is_value_pick",
        "total_points", "goals_scored", "assists",
        "clean_sheets", "selected_by_percent"
    ]].rename(columns={
        "position_name":     "Pos",
        "player_name":       "Player",
        "plays_for":         "Team",
        "price_m":           "Price",
        "fpl_form":          "Form",
        "form_tier":         "Tier",
        "fpl_score":         "FPL Score",
        "fixture_gw1":       f"GW{gw1}",
        "fixture_gw2":       f"GW{gw2}",
        "fixture_gw3":       f"GW{gw3}",
        "fixture_gw4":       f"GW{gw4}",
        "fixture_gw5":       f"GW{gw5}",
        "availability_status": "Status",
        "is_value_pick":     "Value?",
        "total_points":      "Pts",
        "goals_scored":      "G",
        "assists":           "A",
        "clean_sheets":      "CS",
        "selected_by_percent": "Ownership%"
    })

    # Color the FPL score column
    st.dataframe(
        display_df.style.background_gradient(
            subset=["FPL Score"],
            cmap="RdYlGn"
        ).format({
            "Price": "£{:.1f}m",
            "Form": "{:.1f}",
            "FPL Score": "{:.2f}",
            "Ownership%": "{:.1f}%"
        }),
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

    player_row = filtered[filtered["player_name"] == selected_player].iloc[0]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("FPL Score",    f"{player_row['fpl_score']:.2f}")
    c2.metric("Form",         f"{player_row['fpl_form']:.1f}")
    c3.metric("Price",        f"£{player_row['price_m']:.1f}m")
    c4.metric("Total points", player_row['total_points'])
    c5.metric("Ownership",    f"{player_row['selected_by_percent']:.1f}%")

    st.markdown(f"**Next 5 fixtures:** {player_row['fixture_gw1']} → {player_row['fixture_gw2']} → {player_row['fixture_gw3']} → {player_row['fixture_gw4']} → {player_row['fixture_gw5']}")

# --- FOOTER ---
st.divider()
st.caption("Data source: FPL Official API · Transformed with dbt on Databricks · Built by Yashwanth Reddy")
