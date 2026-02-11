from flask import Flask, request, jsonify
from flask_cors import CORS
import pypdf
import json
import re
import os
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

app = Flask(__name__)
# Allow CORS for all domains with explicit resource configuration
CORS(app, resources={r"/*": {"origins": "*"}})

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def extract_text_from_pdf(file_stream):
    try:
        reader = pypdf.PdfReader(file_stream)
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        return text
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return ""

def analyze_with_ai(text):
    if not GEMINI_API_KEY:
        print("⚠️ No API Key found.")
        return None

    # Priorities based on available models
    model_options = [
        'gemini-2.5-flash',
        'gemini-2.0-flash',
        'gemini-flash-latest',
        'gemini-1.5-flash',
        'gemini-pro'
    ]

    model = None
    
    # Try to initialize a working model
    for model_name in model_options:
        try:
            variants = [model_name, f"models/{model_name}"]
            for variant in variants:
                try:
                    model = genai.GenerativeModel(variant)
                    break
                except:
                    continue
            if model: break
        except Exception as e:
            continue

    if not model:
        print("❌ Could not find a valid Gemini model from the list.")
        return None

    try:
        # Define the JSON structure separately using a Python dictionary
        # This prevents syntax errors related to braces in f-strings
        response_schema = {
            "summary": ["Point 1", "Point 2", "Point 3", "Point 4", "Point 5"],
            "risks": [
                {
                    "id": 1, "type": "High", "category": "Privacy",
                    "title": "Risk Title", "explanation": "Why risky",
                    "snippet": "Exact quote from text"
                }
            ]
        }
        
        # Convert schema to string safely
        schema_str = json.dumps(response_schema)

        # Construct prompt using standard string concatenation
        # This avoids the "triple quotes mess" and ensures safe parsing
        prompt = (
            "You are a legal AI. Output valid JSON only. Do not use Markdown blocks. "
            "Exactly five points and do not number them. "
            "For risks, provide id, type (High/Medium/Low), category (e.g. Privacy, Liability), title, explanation, and a snippet from the text.\n\n"
            "Make the summary concise and the risks specific.\n\n"
            "Follow this JSON structure exactly:\n" + schema_str + "\n\n"
            "CONTRACT TEXT:\n" + text[:30000]
        )
        
        response = model.generate_content(prompt)
        json_str = response.text.strip()
        
        # Remove markdown code blocks if present
        if json_str.startswith("```"):
            clean_json = re.sub(r'^```json\s*|\s*```$', '', json_str, flags=re.MULTILINE)
            json_str = clean_json.strip()
            
        return json.loads(json_str)

    except Exception as e:
        print(f"AI Error: {e}")
        return None

def analyze_risks_fallback(text):
    # FALLBACK REGEX MODE
    risks = []
    id_counter = 1
    keywords = {
        "arbitration": {"type": "High", "category": "Legal Recourse", "explanation": "Forced arbitration clause detected."},
        "indemnify": {"type": "High", "category": "Liability", "explanation": "You may be liable for company costs."},
        "sell": {"type": "High", "category": "Privacy", "explanation": "Data selling clause detected."},
        "damages": {"type": "Medium", "category": "Liability", "explanation": "Limitation of liability detected."},
        "termination": {"type": "Medium", "category": "Operational", "explanation": "Check termination rights."}
    }
    
    for word, info in keywords.items():
        for match in re.finditer(r'\b' + re.escape(word) + r'\b', text, re.IGNORECASE):
            start = max(0, match.start() - 40)
            end = min(len(text), match.end() + 60)
            snippet = text[start:end].replace('\n', ' ').strip()
            
            risks.append({
                "id": id_counter,
                "type": info['type'],
                "category": info['category'],
                "title": f"Clause regarding '{word}'",
                "explanation": info['explanation'],
                "snippet": snippet
            })
            id_counter += 1
            if id_counter > 6: break
            
    return risks

# --- ROUTE 1: HEALTH CHECK (GET /) ---
@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "live", "message": "LegalLens Backend is Running!"}), 200

# --- ROUTE 2: ANALYSIS (POST /analyze) ---
# Updated to bind to host 0.0.0.0 and accept OPTIONS for CORS preflight
@app.route('/analyze', methods=['GET', 'POST', 'OPTIONS'])
def analyze_endpoint():
    # Handle GET requests for testing
    if request.method == 'GET':
        return jsonify({"status": "waiting", "message": "Send a POST request with a file to analyze."}), 200
        
    # Handle OPTIONS requests (Pre-flight check)
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    try:
        text = ""
        if file.filename.lower().endswith('.pdf'):
            text = extract_text_from_pdf(file.stream)
        else:
            text = file.stream.read().decode('utf-8', errors='ignore')
            
        if not text:
            return jsonify({"error": "Could not extract text"}), 422

        # Try AI
        print("Attempting AI analysis...")
        ai_result = analyze_with_ai(text)
        
        if ai_result:
            return jsonify({
                "fileName": file.filename,
                "text": text,
                "summary": ai_result.get("summary", []),
                "risks": ai_result.get("risks", [])
            })
        
        # Fallback
        print("Using Fallback Mode")
        risks = analyze_risks_fallback(text)
        summary = ["AI Analysis unavailable.", "Using keyword matching.", "Review document manually.", "Check API Key configuration.", "Standard legal terms found."]
        
        return jsonify({
            "fileName": file.filename,
            "text": text,
            "summary": summary,
            "risks": risks
        })

    except Exception as e:
        print(f"Server Error: {e}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    # Running on 0.0.0.0 ensures the server is accessible externally/across network
    app.run(debug=True, port=5000, host='0.0.0.0')