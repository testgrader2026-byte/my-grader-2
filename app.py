import streamlit as st
import pandas as pd
from PIL import Image
import json
import time
import io
import base64
from openai import OpenAI, RateLimitError

# --- CONFIGURATION ---
st.set_page_config(page_title="AI Exam Dashboard", layout="wide")

MASTER_PASSWORD = "your_password" # Change this!

# --- GITHUB MODELS SETUP ---
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

def analyze_exam_paper(base64_image, model_name):
    """Sends the image to the specified model and returns the JSON data."""
    prompt = """
    You are an expert data extractor reading an exam cover page.
    Carefully analyze the image and extract:
    1. The 'Index Number'.
    2. The student's 'Name' (handwritten).
    3. Look at the marks table. Extract ALL the numerical marks written in the column. Ignore dashes or empty spaces.
    
    Return strictly in this JSON format:
    {
        "name": "extracted name",
        "index": "extracted index",
        "marks": [list of integers extracted from the table]
    }
    """
    
    response = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                ],
            }
        ],
        model=model_name,
        response_format={ "type": "json_object" },
        temperature=0.1 
    )
    return json.loads(response.choices[0].message.content)

if check_password():
    st.sidebar.title("⚙️ Settings")
    divisor = st.sidebar.number_input("Divide final sum by:", value=10.0)

    st.title("📝 AI Exam Grader (Auto-Fallback Edition)")
    st.markdown("Attempts `gpt-4o` first. If daily limits are hit, smoothly transitions to `gpt-4o-mini`.")
    
    uploaded_files = st.file_uploader("Upload Exam Photos", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

    if uploaded_files and token:
        if st.button(f"🚀 Start Grading {len(uploaded_files)} Papers"):
            results = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Start with the best model
            current_model = "gpt-4o"
            
            for i, file in enumerate(uploaded_files):
                status_text.write(f"Analyzing {file.name} using {current_model}...")
                base64_image = encode_image(file)
                
                try:
                    # Try extracting data
                    data = analyze_exam_paper(base64_image, current_model)
                    used_model = current_model
                    
                except RateLimitError:
                    # If gpt-4o hits the daily limit, catch the error and switch!
                    if current_model == "gpt-4o":
                        st.warning("⚠️ gpt-4o daily limit reached! Switching to gpt-4o-mini for remaining papers.")
                        current_model = "gpt-4o-mini"
                        time.sleep(2) # Brief pause before retrying
                        
                        try:
                            # Retry the exact same file with the mini model
                            data = analyze_exam_paper(base64_image, current_model)
                            used_model = current_model
                        except Exception as e:
                            st.error(f"❌ Both models failed on {file.name}: {e}")
                            continue # Skip to the next file
                    else:
                        st.error("❌ gpt-4o-mini limit also reached! Please try again tomorrow.")
                        break # Stop the whole loop
                        
                except Exception as e:
                    st.error(f"❌ Unexpected Error on {file.name}: {e}")
                    continue
                
                # --- PYTHON HANDLES THE MATH ---
                raw_marks = data.get("marks", [])
                clean_marks = [int(m) for m in raw_marks if isinstance(m, (int, float)) or (isinstance(m, str) and m.isdigit())]
                
                total_sum = sum(clean_marks)
                final_score = total_sum / divisor
                
                results.append({
                    "File Name": file.name,
                    "Index": data.get("index", "N/A"),
                    "Name": data.get("name", "N/A"),
                    "Extracted Marks List": str(clean_marks),
                    "Total Sum": total_sum,
                    "Final Calculated Score": final_score,
                    "Model Used": used_model # Tracks which AI graded this specific paper
                })
                
                st.success(f"✅ {data.get('name', 'Unknown')} graded: Score {final_score} ({used_model})")
                
                # Safety delay for free tier rate limits
                time.sleep(5) 
                progress_bar.progress((i + 1) / len(uploaded_files))

            status_text.write("🎉 Grading Complete!")

            # --- TABLE & DOWNLOAD ---
            if results:
                df = pd.DataFrame(results)
                st.dataframe(df)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    df.to_excel(writer, index=False)
                st.download_button("📥 Download Excel", data=output.getvalue(), file_name="accurate_marks.xlsx")
