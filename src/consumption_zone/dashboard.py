import logging
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import clickhouse_connect
import torch
from PIL import Image
import joblib
from transformers import CLIPProcessor, CLIPModel
from src.utils import require_env

# Environment config
st.set_page_config(page_title="Live Health Monitor", layout="wide")

# Clickhouse helper
@st.cache_resource
def get_clickhouse_client():
    """Establish connection to ClickHouse."""
    return clickhouse_connect.get_client(
        host=require_env("CLICKHOUSE_HOST"),
        port=int(require_env("CLICKHOUSE_PORT")),
        user=require_env("CLICKHOUSE_USER"),
        password=require_env("CLICKHOUSE_PASSWORD")
    )

@st.cache_resource
def load_ai_models():
    """Load CLIP encoder and Linear Classifier into memory once."""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device)
    clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    classifier = joblib.load("src/models/cv_classifier.joblib")
    return device, clip_model, clip_processor, classifier

def fetch_data(query: str) -> pd.DataFrame:
    """Fetch data as pandas df."""
    client = get_clickhouse_client()
    return client.query_df(query)

# DB variables
EXPLOITATION_DB = require_env("CLICKHOUSE_EXPLOITATION_DB")
TRUSTED_DB = require_env("CLICKHOUSE_TRUSTED_DB")

# UI header
st.title("Personal Patient Health Dashboard")
st.markdown("Monitor your real-time vitals, historical health trends, and run AI diagnostics.")
st.divider()

# Sidebar
with st.sidebar:
    st.header("Settings")
    # Fetch devices
    devices_df = fetch_data(f"SELECT DISTINCT device_id FROM {EXPLOITATION_DB}.wearable_statistical_profiles FINAL ORDER BY device_id ASC")
    
    if devices_df.empty:
        st.error("No device data found. Please run the data pipeline.")
        st.stop()
        
    device_list = devices_df['device_id'].tolist()
    selected_device = st.selectbox("Select Wearable Device ID:", device_list)

    # Maps the 5 devices to 5 distinct fake patient profiles
    # Just for the demo as we have only one patient with all the data
    mock_profiles = [
        {"family_name": "Smith", "given_name": "James", "gender_code": "Male", "birth_date": "1982-05-14"},
        {"family_name": "Johnson", "given_name": "Sarah", "gender_code": "Female", "birth_date": "1990-11-23"},
        {"family_name": "Garcia", "given_name": "Carlos", "gender_code": "Male", "birth_date": "1975-08-09"},
        {"family_name": "Lee", "given_name": "Emma", "gender_code": "Female", "birth_date": "1988-02-17"},
        {"family_name": "Chen", "given_name": "Wei", "gender_code": "Male", "birth_date": "1995-07-30"}
    ]

    device_idx = device_list.index(selected_device) % len(mock_profiles)
    patient = mock_profiles[device_idx]
    
    st.divider()
    st.header("👤 Patient Profile")
    st.write(f"**Name:** {patient['given_name']} {patient['family_name']}")
    st.write(f"**Gender:** {patient['gender_code']}")
    st.write(f"**DOB:** {patient['birth_date']}")

# Main layout
tab_monitoring, tab_diagnostics = st.tabs(["Vitals Monitoring", "AI Diagnostic Assistant"])


# TAB 1: VITALS MONITORING
with tab_monitoring:
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
        trends_df['window_start'] = pd.to_datetime(trends_df['window_start'])

        tab_hr, tab_bp, tab_temp = st.tabs(["Heart Rate & SpO2", "Blood Pressure", "Temperature & Activity"])

        with tab_hr:
            fig_hr = px.line(trends_df, x='window_start', y='avg_heart_rate_bpm', title="Average Heart Rate over Time")
            fig_hr.update_traces(line_color='#FF4B4B')
            st.plotly_chart(fig_hr, use_container_width=True)

            fig_spo2 = px.line(trends_df, x='window_start', y='min_spo2_pct', title="Minimum SpO2 (%) over Time")
            fig_spo2.update_traces(line_color='#0068C9')
            st.plotly_chart(fig_spo2, use_container_width=True)

        with tab_bp:
            fig_bp = go.Figure()
            fig_bp.add_trace(go.Scatter(x=trends_df['window_start'], y=trends_df['avg_bp_sys'], mode='lines', name='Systolic (mmHg)', line=dict(color='red')))
            fig_bp.add_trace(go.Scatter(x=trends_df['window_start'], y=trends_df['avg_bp_dia'], mode='lines', name='Diastolic (mmHg)', line=dict(color='blue')))
            fig_bp.update_layout(title="Blood Pressure Trends", xaxis_title="Time", yaxis_title="mmHg")
            st.plotly_chart(fig_bp, use_container_width=True)

        with tab_temp:
            fig_temp = px.line(trends_df, x='window_start', y='avg_skin_temperature_c', title="Skin Temperature (°C)")
            fig_temp.update_traces(line_color='#FF8C00')
            st.plotly_chart(fig_temp, use_container_width=True)
            
            fig_steps = px.bar(trends_df, x='window_start', y='avg_steps_last_minute', title="Activity (Steps per Minute)")
            fig_steps.update_traces(marker_color='#29B5E8')
            st.plotly_chart(fig_steps, use_container_width=True)
    else:
        st.warning("No recent vital trends found for this device.")


# TAB 2: AI DIAGNOSTICS
with tab_diagnostics:
    st.subheader("Image Analysis")
    st.markdown("Upload a DICOM (converted to PNG) or standard image scan to obtain a prediction by our AI model.")

    # Load AI models in the background
    with st.spinner("Waking up AI models..."):
        device, clip_model, clip_processor, classifier = load_ai_models()

    uploaded_file = st.file_uploader("Choose a medical image...", type=["png", "jpg", "jpeg"])

    if uploaded_file is not None:
        # Use columns to put the image on the left and the results on the right
        col_img, col_res = st.columns(2)
        
        with col_img:
            image = Image.open(uploaded_file).convert("RGB")
            st.image(image, caption="Uploaded Scan", use_column_width=True)
        
        with col_res:
            st.write("### Diagnostics")
            if st.button("Run AI Analysis", type="primary"):
                with st.spinner("Extracting features and running inference..."):
                    
                    # Generate the embedding using CLIP
                    with torch.no_grad():
                        inputs = clip_processor(images=image, return_tensors="pt").to(device)
                        image_features = clip_model.get_image_features(**inputs)
                        image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)
                        embedding = image_features.cpu().numpy()
                    
                    # Predict using the Linear Classifier
                    prediction = classifier.predict(embedding)[0]
                    probability = classifier.predict_proba(embedding)[0].max() * 100
                    
                    # Display the result (Checking for 1 instead of "positive" due to previous label mapping)
                    if prediction == 1:
                        st.error(f"**Result:** Positive for anomalies ({probability:.1f}% confidence)")
                    else:
                        st.success(f"**Result:** Negative / Clear ({probability:.1f}% confidence)")