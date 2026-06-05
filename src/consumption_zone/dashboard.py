import logging
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import clickhouse_connect
from src.utils import require_env

# Page config
st.set_page_config(page_title="Live Health Monitor", layout="wide")

@st.cache_resource
def get_clickhouse_client():
    """Establish connection to ClickHouse."""
    return clickhouse_connect.get_client(
        host=require_env("CLICKHOUSE_HOST"),
        port=int(require_env("CLICKHOUSE_PORT")),
        user=require_env("CLICKHOUSE_USER"),
        password=require_env("CLICKHOUSE_PASSWORD")
    )

def fetch_data(query: str) -> pd.DataFrame:
    """Fetch data as pandas df."""
    client = get_clickhouse_client()
    return client.query_df(query)

# DB variables
EXPLOITATION_DB = require_env("CLICKHOUSE_EXPLOITATION_DB")
TRUSTED_DB = require_env("CLICKHOUSE_TRUSTED_DB")

# UI Header
st.title("Personal Patient Health Dashboard")
st.markdown("Monitor your real-time vitals and historical health trends.")
st.divider()

# Sidebar: device/patient Selector
with st.sidebar:
    st.header("Settings")
    # Fetch devices
    devices_df = fetch_data(f"SELECT DISTINCT device_id FROM {EXPLOITATION_DB}.wearable_statistical_profiles FINAL ORDER BY device_id ASC")
    
    if devices_df.empty:
        st.error("No device data found. Please run the data pipeline.")
        st.stop()
        
    device_list = devices_df['device_id'].tolist()
    selected_device = st.selectbox("Select Wearable Device ID:", device_list)

    # Fetch a random FHIR profile to pair with this device
    demo_df = fetch_data(f"""
        SELECT family_name, given_name, gender_code, birth_date 
        FROM {EXPLOITATION_DB}.patient_demographics FINAL 
        WHERE family_name != 'Unknown' 
        LIMIT 1 OFFSET {int(selected_device) % 5} -- Cycles through valid names
    """)
    
    st.divider()
    st.header("Patient Profile")
    if not demo_df.empty:
        patient = demo_df.iloc[0]
        st.write(f"**Name:** {patient['given_name']} {patient['family_name']}")
        st.write(f"**Gender:** {patient['gender_code'].capitalize()}")
        st.write(f"**DOB:** {patient['birth_date']}")
    else:
        st.write("Profile data unavailable.")

# Statistical profiles
st.subheader("Historical Baselines")
profile_df = fetch_data(f"""
    SELECT historical_mean_heart_rate, historical_std_heart_rate, historical_mean_spo2, total_baseline_records 
    FROM {EXPLOITATION_DB}.wearable_statistical_profiles FINAL 
    WHERE device_id = '{selected_device}'
""")

if not profile_df.empty:
    profile = profile_df.iloc[0]
    col1, col2, col3, col4 = st.columns(4)
    
    col1.metric("Average Heart Rate", f"{profile['historical_mean_heart_rate']:.1f} BPM", delta="Normal")
    col2.metric("HR Variance (Std Dev)", f"± {profile['historical_std_heart_rate']:.2f} BPM")
    col3.metric("Average SpO2", f"{profile['historical_mean_spo2']:.1f} %", delta="Healthy")
    col4.metric("Total Records Analyzed", f"{profile['total_baseline_records']:,}")
else:
    st.info("No baseline profiles found for this device.")

st.divider()

# Trends (wearable aggregates)
st.subheader("Recent Vital Trends")
trends_df = fetch_data(f"""
    SELECT window_start, avg_heart_rate_bpm, min_spo2_pct, avg_bp_sys, avg_bp_dia, avg_skin_temperature_c, avg_steps_last_minute 
    FROM {TRUSTED_DB}.wearable_aggregates FINAL 
    WHERE device_id = '{selected_device}' 
    ORDER BY window_start ASC
""")

if not trends_df.empty:
    # Ensure datetime format
    trends_df['window_start'] = pd.to_datetime(trends_df['window_start'])

    # Create tabs for different charts to keep UI clean
    tab1, tab2, tab3 = st.tabs(["Heart Rate & SpO2", "Blood Pressure", "Temperature & Activity"])

    with tab1:
        fig_hr = px.line(trends_df, x='window_start', y='avg_heart_rate_bpm', title="Average Heart Rate over Time")
        fig_hr.update_traces(line_color='#FF4B4B')
        st.plotly_chart(fig_hr, use_container_width=True)

        fig_spo2 = px.line(trends_df, x='window_start', y='min_spo2_pct', title="Minimum SpO2 (%) over Time")
        fig_spo2.update_traces(line_color='#0068C9')
        st.plotly_chart(fig_spo2, use_container_width=True)

    with tab2:
        fig_bp = go.Figure()
        fig_bp.add_trace(go.Scatter(x=trends_df['window_start'], y=trends_df['avg_bp_sys'], mode='lines', name='Systolic (mmHg)', line=dict(color='red')))
        fig_bp.add_trace(go.Scatter(x=trends_df['window_start'], y=trends_df['avg_bp_dia'], mode='lines', name='Diastolic (mmHg)', line=dict(color='blue')))
        fig_bp.update_layout(title="Blood Pressure Trends", xaxis_title="Time", yaxis_title="mmHg")
        st.plotly_chart(fig_bp, use_container_width=True)

    with tab3:
        fig_temp = px.line(trends_df, x='window_start', y='avg_skin_temperature_c', title="Skin Temperature (°C)")
        fig_temp.update_traces(line_color='#FF8C00')
        st.plotly_chart(fig_temp, use_container_width=True)
        
        fig_steps = px.bar(trends_df, x='window_start', y='avg_steps_last_minute', title="Activity (Steps per Minute)")
        fig_steps.update_traces(marker_color='#29B5E8')
        st.plotly_chart(fig_steps, use_container_width=True)

else:
    st.warning("No recent vital trends found for this device.")