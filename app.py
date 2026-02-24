import streamlit as st
import pandas as pd
from PIL import Image, ImageEnhance, ImageFilter
import json
import time
import io
import base64
import qrcode
from openai import OpenAI
from mistralai import Mistral
from google.oauth2 import service_account
from google.cloud import vision

# ====================== CONFIG ======================
st.set_page_config(page_title="Ultimate Free AI Exam Grader", layout="wide")
MASTER_PASSWORD = "your_password"   # ← CHANGE THIS
APP_URL = "https://your-app-name.streamlit.app"  # ← UPDATE AFTER DEPLOY

# ====================== FREE CLIENTS ======================
github_token = st.secrets.get("GITHUB_TOKEN", "")
mistral_key = st.secrets.get("MISTRAL_KEY", "")   # ← Add this in secrets (free tier)
openai_client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=github_token)
mistral_client = Mistral(api_key=mistral_key) if mistral_key else None

def get_gcp_client():
    gcp_creds = dict(st.secrets["gcp_service_account"])
    credentials = service_account.Credentials.from_service_account_info(gcp_creds)
    return vision.ImageAnnotatorClient(credentials=credentials)

def encode_image(image_file):
    return base64.b64encode(image_file.getvalue()).decode("utf-8")

def sharpen_image(image_bytes):
    """Makes red ink & handwriting clearer for vision models"""
    img = Image.open(io.BytesIO(image_bytes))
    img = img.filter(ImageFilter.SHARPEN)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.6)
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(1.1)
    byte_arr = io.BytesIO()
    img.save(byte_arr, format='JPEG', quality=95)
    return byte_arr.getvalue(), encode_image(byte_arr)

# ====================== STRONG PROMPT (tailored for your A/L papers) ======================
EXAM_PROMPT = """You are an expert Sri Lankan A/L Combined Mathematics examiner.

This is a real G.C.E. A/L Combined Mathematics II – Paper 07 answer script.
Student wrote name and index at top.
Marks are handwritten in RED PEN inside the big table (Section A: 1-10, Section B: 11-16).

Extract exactly:
- Clean student full name
- Index number (as string)
- Exactly 16 marks in order (question 1 to 16)
  → Use the exact red number
  → "-" or blank or crossed = 0
  → Decimals like 2.5 or ½ are OK

Return ONLY valid JSON:
{
  "name": "Full Name",
  "index": "IndexHere",
  "marks": [1, 1, 0, 10, 2.5, 0, ...]   // exactly 16 numbers
}"""

def extract_with_vision(client, model, image_b64):
    response = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": EXAM_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
            ]
        }],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=1500
    )
    return json.loads(response.choices[0].message.content)

# ====================== FREE TIERS ======================
def tier_1_gpt4o_vision(image_b64):
    return extract_with_vision(openai_client, "gpt-4o", image_b64)

def tier_2_gpt4o_mini_vision(image_b64):
    return extract_with_vision(openai_client, "gpt-4o-mini", image_b64)

def tier_3_mistral_pixtral(image_b64):
    if not mistral_client:
        raise Exception("No Mistral key")
    response = mistral_client.chat.complete(
        model="pixtral-12b-2409",
        messages=[{"role": "user", "content": [
            {"type": "text", "text": EXAM_PROMPT},
            {"type": "image_url", "image_url": f"data:image/jpeg;base64,{image_b64}"}
        ]}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

def tier_4_google_hybrid(image_bytes):
    """Google Vision OCR (free 1000/month) + GPT-4o-mini parser"""
    gcp_client = get_gcp_client()
    image = vision.Image(content=image_bytes)
    image_context = vision.ImageContext(language_hints=['en'])
    
    response = gcp_client.document_text_detection(image=image, image_context=image_context)
    if response.error.message:
        raise Exception(response.error.message)
    
    raw_ocr = response.full_text_annotation.text.strip()
    
    # Same strong prompt but give raw OCR to GPT-4o-mini
    prompt = EXAM_PROMPT + f"\n\nRAW GOOGLE OCR TEXT:\n{raw_ocr}"
    
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.0
    )
    return json.loads(response.choices[0].message.content)

# ====================== MAIN APP ======================
if "authenticated" not in st.session_state:
    pwd = st.text_input("Enter Master Password", type="password")
    if pwd == MASTER_PASSWORD:
        st.session_state.authenticated = True
        st.rerun()
else:
    st.sidebar.title("⚙️ Free Settings")
    divisor = st.sidebar.number_input("Divide total by:", value=10.0, step=0.5)
    
    qr = qrcode.make(APP_URL)
    img_byte_arr = io.BytesIO()
    qr.save(img_byte_arr, format='PNG')
    st.sidebar.image(img_byte_arr.getvalue(), caption="Scan to grade on phone")

    st.title("📝 Ultimate FREE AI Exam Grader 2026")
    st.caption("100% free • GPT-4o Vision first • Google Vision backup")

    uploaded_files = st.file_uploader("Upload Exam Photos", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

    if uploaded_files and st.button("🚀 Start Grading (Free)"):
        results = []
        progress_bar = st.progress(0)

        for i, file in enumerate(uploaded_files):
            image_bytes = file.getvalue()
            sharpened_bytes, image_b64 = sharpen_image(image_bytes)

            data = None
            used_tier = "Failed"

            # === FREE WATERFALL (highest accuracy first) ===
            try:
                data = tier_1_gpt4o_vision(image_b64)
                used_tier = "Tier 1: GPT-4o Vision (GitHub Free)"
            except:
                try:
                    data = tier_2_gpt4o_mini_vision(image_b64)
                    used_tier = "Tier 2: GPT-4o-mini Vision"
                except:
                    try:
                        data = tier_3_mistral_pixtral(image_b64)
                        used_tier = "Tier 3: Mistral Pixtral (Free)"
                    except:
                        try:
                            data = tier_4_google_hybrid(image_bytes)
                            used_tier = "Tier 4: Google Vision + GPT-4o-mini (Free)"
                        except Exception as e:
                            st.error(f"❌ Failed on {file.name}")
                            continue

            # Calculate
            clean_marks = [float(m) if str(m).replace('.', '', 1).replace('-', '', 1).isdigit() else 0.0 
                           for m in data.get("marks", [])]
            total = sum(clean_marks)
            final_score = total / divisor

            results.append({
                "File": file.name,
                "Index": data.get("index", "N/A"),
                "Name": data.get("name", "N/A"),
                "Marks List": str(clean_marks),
                "Total Raw": round(total, 2),
                "Final Score": round(final_score, 2),
                "Engine": used_tier
            })

            st.success(f"✅ {file.name} → {used_tier} | Score: {round(final_score, 2)}")
            time.sleep(1.5)
            progress_bar.progress((i + 1) / len(uploaded_files))

        if results:
            df = pd.DataFrame(results)
            st.dataframe(df, use_container_width=True)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False)
            st.download_button("📥 Download Excel", output.getvalue(), "final_marks.xlsx")
