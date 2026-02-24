import streamlit as st
import pandas as pd
from PIL import Image
import json
import time
import io
import base64
import requests
import qrcode
from openai import OpenAI, RateLimitError
from mistralai import Mistral
from google.oauth2 import service_account
from google.cloud import vision

# --- CONFIGURATION ---
st.set_page_config(page_title="Ultimate AI Exam Grader", layout="wide")
MASTER_PASSWORD = "your_password" # Change this!

# APP URL FOR QR CODE (Update this AFTER you deploy)
APP_URL = "https://your-app-name.streamlit.app"

# --- API CLIENT SETUP ---
# Safely get tokens (won't crash if empty during initial setup)
github_token = st.secrets.get("GITHUB_TOKEN", "")
mistral_key = st.secrets.get("MISTRAL_KEY", "")

# Initialize Clients
openai_client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=github_token)
mistral_client = Mistral(api_key=mistral_key) if mistral_key else None

def get_gcp_client():
    """Authenticates Google Cloud using Streamlit Secrets"""
    gcp_creds = dict(st.secrets["gcp_service_account"])
    credentials = service_account.Credentials.from_service_account_info(gcp_creds)
    return vision.ImageAnnotatorClient(credentials=credentials)

def encode_image(image_file):
    return base64.b64encode(image_file.getvalue()).decode("utf-8")

# --- THE NEW TIERED OCR FUNCTIONS ---

def extract_with_gpt(prompt, text_data=None, image_b64=None, model="gpt-4o"):
    """Helper function to talk to GitHub GPT models"""
    content = [{"type": "text", "text": prompt}]
    if image_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
    if text_data:
        content[0]["text"] += f"\n\nRaw OCR Data: {text_data}"
        
    response = openai_client.chat.completions.create(
        messages=[{"role": "user", "content": content}],
        model=model,
        response_format={ "type": "json_object" },
        temperature=0.0 # 0.0 means maximum accuracy, no guessing
    )
    return json.loads(response.choices[0].message.content)

def tier_1_google_gpt4o(image_bytes):
    """Premium Tier: Google Cloud Vision reads it, GPT-4o formats it."""
    gcp_client = get_gcp_client()
    image = vision.Image(content=image_bytes)
    response = gcp_client.document_text_detection(image=image)
    if response.error.message: 
        raise Exception(f"Google API Error: {response.error.message}")
    
    ocr_text = response.full_text_annotation.text
    prompt = "Extract index, name, and a JSON list of exam marks integers from this raw OCR data. Format: {'name': 'str', 'index': 'str', 'marks': [int]}"
    return extract_with_gpt(prompt, text_data=ocr_text, model="gpt-4o")

def tier_2_mistral(image_b64):
    """Secondary Tier: Mistral Pixtral OCR"""
    prompt = "Extract index, name, and an array of numerical marks from the table. Return strictly JSON: {'name': 'str', 'index': 'str', 'marks': [int]}"
    response = mistral_client.chat.complete(
        model="pixtral-12b-2409",
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": f"data:image/jpeg;base64,{image_b64}"}]}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

def tier_3_gpt4o_vision(image_b64):
    """Emergency Tier: GPT-4o Vision directly"""
    prompt = "Extract index, name, and an array of numerical marks from the table. Return strictly JSON: {'name': 'str', 'index': 'str', 'marks': [int]}"
    return extract_with_gpt(prompt, image_b64=image_b64, model="gpt-4o")

def tier_4_fallback(image_b64):
    """Last Resort Tier: GPT-4o-mini Vision Only"""
    prompt = "Extract index, name, and an array of numerical marks from the table. Return strictly JSON: {'name': 'str', 'index': 'str', 'marks': [int]}"
    return extract_with_gpt(prompt, image_b64=image_b64, model="gpt-4o-mini")

# --- MAIN APP UI ---
if "authenticated" not in st.session_state:
    pwd = st.text_input("Enter Master Password", type="password")
    if pwd == MASTER_PASSWORD: 
        st.session_state.authenticated = True
        st.rerun()
else:
    st.sidebar.title("⚙️ Settings & Tools")
    divisor = st.sidebar.number_input("Divide marks by:", value=10.0)
    
    # Generate and display QR Code
    qr = qrcode.make(APP_URL)
    img_byte_arr = io.BytesIO()
    qr.save(img_byte_arr, format='PNG')
    st.sidebar.image(img_byte_arr.getvalue(), caption="Scan to grade with phone camera")

    st.title("📝 The Ultimate AI Exam Grader")
    uploaded_files = st.file_uploader("Upload Exam Photos", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

    if uploaded_files:
        if st.button("🚀 Start Grading Process"):
            results = []
            progress_bar = st.progress(0)
            
            for i, file in enumerate(uploaded_files):
                image_bytes = file.getvalue()
                image_b64 = encode_image(file)
                data, used_tier = None, "None"
                
                # --- THE NEW WATERFALL LOGIC ---
                try:
                    data = tier_1_google_gpt4o(image_bytes)
                    used_tier = "Tier 1: Google + GPT-4o"
                except Exception as e1:
                    try:
                        data = tier_2_mistral(image_b64)
                        used_tier = "Tier 2: Mistral OCR"
                    except Exception as e2:
                        try:
                            data = tier_3_gpt4o_vision(image_b64)
                            used_tier = "Tier 3: GPT-4o Vision"
                        except Exception as e3:
                            try:
                                data = tier_4_fallback(image_b64)
                                used_tier = "Tier 4: GPT-4o-mini Only"
                            except Exception as e4:
                                st.error(f"❌ All systems failed on {file.name}")
                                continue
                
                # Math Calculation
                clean_marks = [int(m) for m in data.get("marks", []) if str(m).isdigit()]
                final_score = sum(clean_marks) / divisor
                
                results.append({
                    "File Name": file.name,
                    "Index": data.get("index", "N/A"),
                    "Name": data.get("name", "N/A"),
                    "Extracted Marks List": str(clean_marks),
                    "Final Score": final_score,
                    "Engine Used": used_tier
                })
                
                st.success(f"✅ Graded {file.name} using {used_tier}")
                time.sleep(2) # Protects against rate limits
                progress_bar.progress((i + 1) / len(uploaded_files))

            if results:
                df = pd.DataFrame(results)
                st.dataframe(df)
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    df.to_excel(writer, index=False)
                st.download_button("📥 Download Excel", data=output.getvalue(), file_name="final_marks.xlsx")
