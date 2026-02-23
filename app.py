import streamlit as st
import google.generativeai as genai
import pandas as pd
from PIL import Image
import json
import time
import io

# --- CONFIGURATION ---
st.set_page_config(page_title="AI Exam Dashboard", layout="wide")

MASTER_PASSWORD = "your_password" 

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

if check_password():
    st.sidebar.title("⚙️ Settings")
    api_key = st.sidebar.text_input("Gemini API Key", type="password", value=st.secrets.get("GEMINI_API_KEY", ""))
    divisor = st.sidebar.number_input("Divide marks by:", value=10.0)

    st.title("📝 AI Exam Grader (Stable Version)")
    uploaded_files = st.file_uploader("Upload Exam Photos", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

    if uploaded_files and api_key:
        genai.configure(api_key=api_key)
        # Switching to the 1.5 Stable model for better Free Tier reliability
        model = genai.GenerativeModel('gemini-1.5-flash')

        if st.button(f"🚀 Start Grading {len(uploaded_files)} Papers"):
            results = []
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, file in enumerate(uploaded_files):
                status_text.text(f"Processing {file.name} ({i+1}/{len(uploaded_files)})...")
                img = Image.open(file)
                
                prompt = f"""
                Return ONLY a JSON:
                1. Identify Name and Index.
                2. Sum all RED ink marks.
                3. Double-check the addition.
                {{ "name": "str", "index": "str", "raw_total": 0.0, "final": 0.0 }}
                Divide raw_total by {divisor} for final.
                """

                # --- SMART RETRY LOGIC ---
                success = False
                for attempt in range(3): # Try 3 times
                    try:
                        response = model.generate_content([prompt, img])
                        clean_json = response.text.replace("```json", "").replace("```", "").strip()
                        data = json.loads(clean_json)
                        data["Filename"] = file.name
                        results.append(data)
                        st.success(f"✅ {data['name']} graded.")
                        success = True
                        break # Exit retry loop on success
                    except Exception as e:
                        if "429" in str(e):
                            st.warning(f"🕒 Google limit hit. Waiting 15 seconds to retry... (Attempt {attempt+1})")
                            time.sleep(15)
                        else:
                            st.error(f"❌ Error: {e}")
                            break
                
                # --- SAFE DELAY ---
                # This 10-second sleep is the "secret" to not getting blocked
                time.sleep(10)
                progress_bar.progress((i + 1) / len(uploaded_files))

            # --- EXPORT ---
            st.write("### 📊 Final Results")
            df = pd.DataFrame(results)
            st.dataframe(df)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False)
            st.download_button("📥 Download Excel", data=output.getvalue(), file_name="marks.xlsx")
