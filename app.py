# app.py
import os
import uuid
import base64
import mimetypes
import logging
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
import requests
import smtplib
from email.mime.text import MIMEText
 
# Load .env if present
load_dotenv()
 
# -------- Configuration ----------
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = "uploads"
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
 
# Default Flowise URL (you said this URL connects to Flowise)
FLOWISE_API_URL = os.getenv(
    "FLOWISE_API_URL",
    "http://localhost:3000/api/v1/prediction/e2b5a8fb-f99c-4818-a338-53e439ff1f79"
)
FLOWISE_API_KEY = os.getenv("FLOWISE_API_KEY")  # optional Bearer token
 
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_PASS")  # Use a Gmail App Password if using Gmail
 
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}
logging.basicConfig(level=logging.INFO)
 
 
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT
 
 
# ----------------------------
# Home page (optional)
# ----------------------------
@app.route("/", methods=["GET"])
def index():
    # put your index.html in templates/ if you render a UI
    return render_template("index.html")
 
 
# ----------------------------
# Ask bot (image + question)
# Accepts: multipart/form-data with fields:
#   - image : file (optional but supported)
#   - question : text (required)
# Returns Flowise response as JSON
# ----------------------------
@app.route("/ask", methods=["POST"])
def ask_bot():
    # Validate question
    question = request.form.get("question")
    if not question:
        return jsonify({"error": "question field is required"}), 400
 
    file = request.files.get("image")
    uploads = []
 
    if file and file.filename:
        if not allowed_file(file.filename):
            return jsonify({"error": "file type not allowed"}), 400
 
        filename = secure_filename(file.filename)
        # Save locally (optional) — useful for debugging / logs
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
 
        # Read bytes and create data URI base64 per Flowise 'uploads' schema
        with open(filepath, "rb") as f:
            raw = f.read()
        mime = file.mimetype or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        b64 = base64.b64encode(raw).decode("utf-8")
        data_uri = f"data:{mime};base64,{b64}"
 
        uploads.append({
            "type": "file",
            "name": filename,
            "data": data_uri,
            "mime": mime
        })
 
    # Build payload per Flowise prediction API (uploads as array allowed). See docs. :contentReference[oaicite:1]{index=1}
    payload = {
        "question": question,
        "uploads": uploads,
        "overrideConfig": {
            "sessionId": str(uuid.uuid4())  # unique session for this request
        }
    }
 
    headers = {"Content-Type": "application/json"}
    if FLOWISE_API_KEY:
        headers["Authorization"] = f"Bearer {FLOWISE_API_KEY}"
 
    try:
        resp = requests.post(FLOWISE_API_URL, json=payload, headers=headers, timeout=60)
    except requests.RequestException as e:
        logging.exception("Failed to call Flowise prediction endpoint")
        return jsonify({"error": "failed to reach Flowise", "detail": str(e)}), 502
 
    # Forward Flowise response (try JSON)
    try:
        flowise_data = resp.json()
    except ValueError:
        logging.error("Non-JSON response from Flowise: %s", resp.text[:500])
        return jsonify({"error": "invalid response from flowise", "raw": resp.text}), 500
 
    # normalise common reply fields
    answer = flowise_data.get("text") or flowise_data.get("answer") or flowise_data
 
    return jsonify({
        "success": True,
        "answer": answer,
        "raw": flowise_data
    }), resp.status_code if resp.status_code < 400 else 200
 
 
# ----------------------------
# Send Itinerary (only when called)
# Accepts JSON:
#   { "email": "user@example.com", "itinerary": "text body", "subject": optional }
# ----------------------------
@app.route("/send_itinerary", methods=["POST"])
def send_itinerary():
    data = request.get_json(force=True, silent=True) or {}
    recipient = data.get("email")
    itinerary = data.get("itinerary", "")
    subject = data.get("subject", "Travel Guide Bot: Landmark Details")
 
    if not recipient:
        return jsonify({"error": "email is required"}), 400
 
    if not GMAIL_USER or not GMAIL_PASS:
        logging.error("Email credentials not configured on server environment")
        return jsonify({"error": "email credentials not configured"}), 500
 
    msg = MIMEText(itinerary, "plain")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = recipient
 
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASS)
            server.sendmail(GMAIL_USER, [recipient], msg.as_string())
        return jsonify({"success": True, "status": "Email sent"}), 200
    except Exception as e:
        logging.exception("Failed to send itinerary email")
        return jsonify({"error": "failed to send email", "detail": str(e)}), 500
 
 
# ----------------------------
# Health check
# ----------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200
 
 
if __name__ == "__main__":
    # Use PORT env var in production containers
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
