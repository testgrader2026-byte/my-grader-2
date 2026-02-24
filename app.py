import streamlit as st
import pandas as pd
from PIL import Image
import json
import time
import io
import base64
import qrcode
from openai import OpenAI, RateLimitError
from mistralai import Mistral
from google.oauth2 import service_account
from google.cloud import vision

# --- CONFIGURATION ---
st.set_page_config(page_title="Ultimate AI Exam Grader", layout="wide")
MASTER_PASSWORD = "your_password"  # Change this!
APP_URL = "https://your-app-name.streamlit.app"  # Update after deploy

# --- API CLIENT SETUP ---
github_token = st.secrets.get("GITHUB_TOKEN", "")
mistral_key = st.secrets.get("MISTRAL_KEY", "")

openai_client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=github_token)
mistral_client = Mistral(api_key=mistral_key) if mistral_key else None

def get_gcp_client():
    """Authenticates Google Cloud using Streamlit Secrets"""
    gcp_creds = dict(st.secrets["gcp_service_account"])
    credentials = service_account.Credentials.from_service_account_info(gcp_creds)
    return vision.ImageAnnotatorClient(credentials=credentials)

def encode_image(image_file):
    return base64.b64encode(image_file.getvalue()).decode("utf-8")

# ====================== IMPROVED HELPERS ======================
def extract_with_gpt(prompt, text_data=None, image_b64=None, prefer_model="gpt-4o"):
    """Smart helper: tries preferred model, falls back to gpt-4o-mini on rate limit"""
    models_to_try = [prefer_model]
    if prefer_model == "gpt-4o":
        models_to_try.append("gpt-4o-mini")
    
    for model in models_to_try:
        try:
            content = [{"type": "text", "text": prompt}]
            if image_b64:
                content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
            if text_data:
                content[0]["text"] += f"\n\n--- RAW GOOGLE VISION OCR ---\n{text_data}\n-----------------------------"
            
            response = openai_client.chat.completions.create(
                messages=[{"role": "user", "content": content}],
                model=model,
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=1200
            )
            result = json.loads(response.choices[0].message.content)
            return result, model
        except RateLimitError:
            st.warning(f"⚠️ Rate limit hit on {model} — trying fallback...")
            if model == "gpt-4o-mini":
                raise
            continue
        except Exception as e:
            st.error(f"Error with {model}: {str(e)[:100]}")
            if model == models_to_try[-1]:
                raise
            continue
    raise Exception("All GPT models failed")

# ====================== IMPROVED TIER 1 (YOUR MAIN REQUEST) ======================
def tier_1_google_gpt4o(image_bytes):
    """Tier 1 — Highest accuracy path (as requested):
       • Always uses Google Cloud Vision document_text_detection (best for paper/handwriting)
       • Language hint for English
       • GPT-4o with automatic fallback to gpt-4o-mini on rate limit
       • Very strong cleaning prompt"""
    gcp_client = get_gcp_client()
    image = vision.Image(content=image_bytes)
    
    # Improvement #1: Language hint for English documents/handwriting
    image_context = vision.ImageContext(language_hints=['en'])
    
    response = gcp_client.document_text_detection(
        image=image,
        image_context=image_context
    )
    
    if response.error.message:
        raise Exception(f"Google Vision Error: {response.error.message}")
    
    ocr_text = response.full_text_annotation.text.strip()
    
    if len(ocr_text) < 30:
        raise Exception("Google Vision returned almost no text")

    # Improvement #2: Extremely detailed prompt (Gemini + our testing)
    prompt = """You are an expert OCR post-processor for handwritten/printed student exam answer sheets.

The text below is raw output from Google Cloud Vision DOCUMENT_TEXT_DETECTION on a photo of an exam paper (English).

Your job:
1. Clean common OCR mistakes (1/l/I, 0/O, 5/S, 8/B, 7/T, etc.)
2. Extract:
   - Student full name (cleaned)
   - Index / roll number / registration number (as string)
   - List of individual question marks ONLY (integers, in the exact order they appear in the table)
   
Rules:
- Ignore totals, signatures, printed instructions, question text, headers/footers
- Only include actual per-question scores (typically 0-20 range)
- If a mark is illegible, skip it (do not guess)
- Name and index must be cleaned and capitalized properly

Return STRICTLY valid JSON (nothing else):
{
  "name": "Full Student Name",
  "index": "IndexNumberHere",
  "marks": [5, 8, 0, 9, 7, ...]
}

RAW OCR TEXT:"""

    data, used_model = extract_with_gpt(prompt, text_data=ocr_text, prefer_model="gpt-4o")
    return data, used_model

# ====================== UNCHANGED BACKUP TIERS ======================
def tier_2_mistral(image_b64):
    """Tier 2: Mistral Pixtral (pure vision)"""
    prompt = "Extract index, name, and an array of numerical marks from the table. Return strictly JSON: {'name': 'str', 'index': 'str', 'marks': [int]}"
    response = mistral_client.chat.complete(
        model="pixtral-12b-2409",
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": f"data:image/jpeg;base64,{image_b64}"}
        ]}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

def tier_3_gpt4o_vision(image_b64):
    """Tier 3: GPT-4o Vision directly"""
    prompt = "Extract index, name, and an array of numerical marks from the table. Return strictly JSON: {'name': 'str', 'index': 'str', 'marks': [int]}"
    data, _ = extract_with_gpt(prompt, image_b64=image_b64, prefer_model="gpt-4o")
    return data

def tier_4_fallback(image_b64):
    """Tier 4: GPT-4o-mini Vision only"""
    prompt = "Extract index, name, and an array of numerical marks from the table. Return strictly JSON: {'name': 'str', 'index': 'str', 'marks': [int]}"
    data, _ = extract_with_gpt(prompt, image_b64=image_b64, prefer_model="gpt-4o-mini")
    return data

# ====================== AUTH & UI ======================
if "authenticated" not in st.session_state:
    pwd = st.text_input("Enter Master Password", type="password")
    if pwd == MASTER_PASSWORD:
        st.session_state.authenticated = True
        st.rerun()
else:
    st.sidebar.title("⚙️ Settings & Tools")
    divisor = st.sidebar.number_input("Divide marks by:", value=10.0, step=0.5)
    
    # QR Code
    qr = qrcode.make(APP_URL)
    img_byte_arr = io.BytesIO()
    qr.save(img_byte_arr, format='PNG')
    st.sidebar.image(img_byte_arr.getvalue(), caption="Scan to grade with phone")

    st.title("📝 The Ultimate AI Exam Grader")
    uploaded_files = st.file_uploader("Upload Exam Photos", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

    if uploaded_files:
        if st.button("🚀 Start Grading Process"):
            results = []
            progress_bar = st.progress(0)

            for i, file in enumerate(uploaded_files):
                image_bytes = file.getvalue()
                image_b64 = encode_image(file)
                data = None
                used_tier = "Failed"

                # === NEW WATERFALL WITH SMART TIER 1 ===
                try:
                    data, used_model = tier_1_google_gpt4o(image_bytes)
                    used_tier = f"Tier 1: Google Vision + {used_model.upper()}"
                except Exception as e1:
                    st.warning(f"Tier 1 failed for {file.name} — trying Tier 2...")
                    try:
                        data = tier_2_mistral(image_b64)
                        used_tier = "Tier 2: Mistral Pixtral"
                    except Exception as e2:
                        try:
                            data = tier_3_gpt4o_vision(image_b64)
                            used_tier = "Tier 3: GPT-4o Vision"
                        except Exception as e3:
                            try:
                                data = tier_4_fallback(image_b64)
                                used_tier = "Tier 4: GPT-4o-mini Vision"
                            except Exception as e4:
                                st.error(f"❌ All systems failed on {file.name}")
                                continue

                # Math
                clean_marks = [int(float(m)) for m in data.get("marks", []) 
                               if str(m).replace('.', '', 1).replace('-', '', 1).isdigit()]
                final_score = sum(clean_marks) / divisor

                results.append({
                    "File Name": file.name,
                    "Index": data.get("index", "N/A"),
                    "Name": data.get("name", "N/A"),
                    "Extracted Marks List": str(clean_marks),
                    "Total Questions": len(clean_marks),
                    "Final Score": round(final_score, 2),
                    "Engine Used": used_tier
                })

                st.success(f"✅ Processed {file.name} → {used_tier}")
                time.sleep(1.8)  # Rate-limit safety
                progress_bar.progress((i + 1) / len(uploaded_files))

            if results:
                df = pd.DataFrame(results)
                st.dataframe(df, use_container_width=True)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    df.to_excel(writer, index=False)
                st.download_button(
                    "📥 Download Excel",
                    data=output.getvalue(),
                    file_name="final_marks.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
