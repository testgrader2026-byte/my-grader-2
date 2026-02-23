import streamlit as st
import google.generativeai as genai
import pandas as pd
from PIL import Image
import qrcode
import io
import time
import json

# --- CONFIGURATION ---
st.set_page_config(page_title="AI Exam Dashboard", layout="wide")

# 1. Password Protection
MASTER_PASSWORD = "pizza one" 

def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if not st.session_state.authenticated:
        pwd = st.text_input("Enter Master Password", type="password")
        if pwd == MASTER_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            if pwd: st.error("Wrong password!")
            return False
    return True

if check_password():
    # 2. Sidebar Settings
    st.sidebar.title("⚙️ Settings")
    api_key = st.sidebar.text_input("Gemini API Key", type="password")
    divisor = st.sidebar.number_input("Divide marks by:", value=10.0)
    custom_instr = st.sidebar.text_area("Extra Instructions", "Check for student signature.")

    # 3. QR Code Generator for Mobile Bridge
    st.sidebar.markdown("---")
    st.sidebar.write("📱 **Phone Upload Link**")
    if st.button("Generate QR Code"):
        # Note: You will replace this URL with your actual deployed link later
        url = st.query_params.get("url", "https://your-app.streamlit.app") 
        qr = qrcode.make(url)
        buf = io.BytesIO()
        qr.save(buf)
        st.sidebar.image(buf.getvalue(), caption="Scan with Phone to Upload")

    # 4. Main Interface
    st.title("📝 AI Exam Grader Pro")
    uploaded_files = st.file_uploader("Upload Exam Photos (Up to 200)", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

    if uploaded_files and api_key:
        genai.configure(api_key=api_key)
        # Using Gemini 2.0 Flash for maximum speed and batch stability
        model = genai.GenerativeModel('gemini-2.0-flash')

        if st.button(f"🚀 Start Grading {len(uploaded_files)} Papers"):
            results = []
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, file in enumerate(uploaded_files):
                status_text.text(f"Processing {file.name} ({i+1}/{len(uploaded_files)})...")
                
                try:
                    img = Image.open(file)
                    
                    # High-Accuracy Self-Correction Prompt
                    prompt = f"""
                    Follow this 3-step logic strictly:
                    1. DATA EXTRACTION: Identify 'Student Name' and 'Index Number'.
                    2. GRADING: Sum all red ink marks. List them internally first.
                    3. VERIFICATION: Re-calculate the sum. If it doesn't match, re-scan.
                    4. Custom instruction: {custom_instr}
                    
                    Return ONLY a JSON:
                    {{"name": "str", "index": "str", "raw_total": 0.0, "final": 0.0, "note": "str"}}
                    Divide raw_total by {divisor} for the 'final' result.
                    """
                    
                    response = model.generate_content([prompt, img])
                    clean_json = response.text.replace("```json", "").replace("```", "").strip()
                    data = json.loads(clean_json)
                    data["Filename"] = file.name
                    results.append(data)
                    
                    st.success(f"✅ Graded: {data['name']} (Score: {data['final']})")
                    
                    # 3-second delay to stay within Free Tier limits for large batches
                    time.sleep(3) 
                    
                except Exception as e:
                    st.error(f"❌ Error in {file.name}: {e}")
                
                progress_bar.progress((i + 1) / len(uploaded_files))

            # 5. Export to Excel
            st.write("### 📊 Final Results")
            df = pd.DataFrame(results)
            st.dataframe(df)

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False)
            
            st.download_button(
                label="📥 Download Excel Results",
                data=output.getvalue(),
                file_name="student_marks.xlsx",
                mime="application/vnd.ms-excel"
            )
