import streamlit as st
import pandas as pd
import json
import time
import io
import base64
import qrcode
from openai import OpenAI
from google.oauth2 import service_account
from google.cloud import vision

# --- CONFIGURATION ---
st.set_page_config(page_title="Pro Exam Grader", layout="wide")
MASTER_PASSWORD = "your_password" 
APP_URL = "https://your-app-name.streamlit.app" # Update after deploy

# --- API CLIENT SETUP ---
github_token = st.secrets.get("GITHUB_TOKEN", "")
openai_client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=github_token)

def get_gcp_client():
    gcp_creds = dict(st.secrets["gcp_service_account"])
    credentials = service_account.Credentials.from_service_account_info(gcp_creds)
    return vision.ImageAnnotatorClient(credentials=credentials)

def encode_image(image_file):
    return base64.b64encode(image_file.getvalue()).decode("utf-8")

# --- CORE LOGIC FUNCTIONS ---

def extract_logic(prompt, text_data=None, image_b64=None, model="gpt-4o"):
    """Helper for GPT extraction"""
    content = [{"type": "text", "text": prompt}]
    if image_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
    if text_data:
        content[0]["text"] += f"\n\nRAW DATA FROM GOOGLE OCR: {text_data}"
        
    response = openai_client.chat.completions.create(
        messages=[{"role": "user", "content": content}],
        model=model,
        response_format={ "type": "json_object" },
        temperature=0.0
    )
    return json.loads(response.choices[0].message.content)

def tier_1_google_gpt4o(image_bytes):
    """Google reads the text, GPT-4o thinks about it."""
    gcp_client = get_gcp_client()
    image = vision.Image(content=image_bytes)
    response = gcp_client.document_text_detection(image=image)
    ocr_text = response.full_text_annotation.text
    
    prompt = """
    Extract the student name, index, and ALL numerical marks from the marks table.
    Use the provided RAW OCR text to find the numbers. 
    Return JSON: {"name": "str", "index": "str", "marks": [list of numbers]}
    """
    return extract_logic(prompt, text_data=ocr_text, model="gpt-4o")

def tier_2_gpt4o_vision(image_b64):
    """GPT-4o looks at the image directly if Google fails."""
    prompt = "Look at the image. Extract name, index, and marks from the table. Return JSON: {'name': 'str', 'index': 'str', 'marks': [int]}"
    return extract_logic(prompt, image_b64=image_b64, model="gpt-4o")

def tier_3_fallback(image_b64):
    """Emergency fallback to Mini."""
    prompt = "Extract name, index, and marks. Return JSON: {'name': 'str', 'index': 'str', 'marks': [int]}"
    return extract_logic(prompt, image_b64=image_b64, model="gpt-4o-mini")

# --- UI ---
if "authenticated" not in st.session_state:
    pwd = st.text_input("Password", type="password")
    if pwd == MASTER_PASSWORD: 
        st.session_state.authenticated = True
        st.rerun()
else:
    divisor = st.sidebar.number_input("Divide marks by:", value=10.0)
    
    # QR Code
    qr = qrcode.make(APP_URL)
    buf = io.BytesIO()
    qr.save(buf, format='PNG')
    st.sidebar.image(buf.getvalue(), caption="Scan to use phone camera")

    st.title("🎯 High-Accuracy Exam Grader")
    uploaded_files = st.file_uploader("Upload Exam Photos", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

    if uploaded_files and st.button("🚀 Start Grading"):
        results = []
        for file in uploaded_files:
            img_bytes = file.getvalue()
            img_b64 = encode_image(file)
            
            # --- THE WATERFALL ---
            try:
                data = tier_1_google_gpt4o(img_bytes)
                tier = "Tier 1: Google + GPT-4o"
            except:
                try:
                    data = tier_2_gpt4o_vision(img_b64)
                    tier = "Tier 2: GPT-4o Vision"
                except:
                    data = tier_3_fallback(img_b64)
                    tier = "Tier 3: GPT-4o-mini"

            # Clean the list (Ensures no strings or 0 errors)
            raw_marks = data.get("marks", [])
            clean_marks = []
            for m in raw_marks:
                try: clean_marks.append(float(m))
                except: continue
                
            final_score = sum(clean_marks) / divisor
            
            results.append({
                "Student": data.get("name", "N/A"),
                "Index": data.get("index", "N/A"),
                "Marks Found": str(clean_marks),
                "Final Score": final_score,
                "Model Used": tier
            })
            st.success(f"✅ Graded {file.name} using {tier}")
            time.sleep(2)

        if results:
            df = pd.DataFrame(results)
            st.table(df)
            # Excel Download... (omitted for brevity, keep your old excel code here)
