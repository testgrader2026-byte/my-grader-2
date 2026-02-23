import streamlit as st
import pandas as pd
from PIL import Image
import json
import time
import io
import base64
from openai import OpenAI # Use pip install openai

# --- CONFIGURATION ---
st.set_page_config(page_title="AI Exam Dashboard", layout="wide")

MASTER_PASSWORD = "your_password" 

# --- GITHUB MODELS SETUP ---
# This connects to GitHub's free "GPT-4o-mini"
token = st.secrets.get("GITHUB_TOKEN", "")
client = OpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=token,
)

def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if not st.session_state.authenticated:
        pwd = st.text_input("Enter Master Password", type="password")
        if pwd == MASTER_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        return False
    return True

def encode_image(image_file):
    return base64.b64encode(image_file.read()).decode("utf-8")

if check_password():
    st.sidebar.title("⚙️ Settings")
    divisor = st.sidebar.number_input("Divide marks by:", value=10.0)

    st.title("📝 AI Exam Grader (GitHub Models Edition)")
    uploaded_files = st.file_uploader("Upload Exam Photos", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

    if uploaded_files and token:
        if st.button(f"🚀 Start Grading {len(uploaded_files)} Papers"):
            results = []
            progress_bar = st.progress(0)
            
            for i, file in enumerate(uploaded_files):
                st.write(f"Reading {file.name}...")
                
                # Convert image to Base64 for GPT-4o-mini
                base64_image = encode_image(file)
                
                try:
                    response = client.chat.completions.create(
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": f"Extract Student Name, Index, and Sum of RED marks. Divide sum by {divisor}. Return ONLY JSON: {{'name': 'str', 'index': 'str', 'final': 0.0}}"},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                                ],
                            }
                        ],
                        model="gpt-4o-mini",
                        response_format={ "type": "json_object" }
                    )
                    
                    data = json.loads(response.choices[0].message.content)
                    results.append(data)
                    st.success(f"✅ {data['name']} graded.")
                    
                except Exception as e:
                    st.error(f"❌ Error on {file.name}: {e}")
                
                # Minute limit safety: 15 requests per minute = 1 every 4 seconds
                time.sleep(4)
                progress_bar.progress((i + 1) / len(uploaded_files))

            # --- TABLE & DOWNLOAD ---
            df = pd.DataFrame(results)
            st.dataframe(df)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False)
            st.download_button("📥 Download Excel", data=output.getvalue(), file_name="marks.xlsx")
