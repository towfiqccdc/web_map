from flask import Flask, send_from_directory, request, jsonify
import requests
import os

# --------------------------------------------------
# PATH CONFIGURATION
# --------------------------------------------------

# app.py is inside /server
# BASE_DIR points to the project root
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

FRONTEND_DIR = BASE_DIR


# --------------------------------------------------
# FLASK APP
# --------------------------------------------------

app = Flask(__name__)


# --------------------------------------------------
# FRONTEND
# --------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/CSS/<path:filename>")
def css_files(filename):
    return send_from_directory(
        os.path.join(FRONTEND_DIR, "CSS"),
        filename
    )


@app.route("/JS/<path:filename>")
def js_files(filename):
    return send_from_directory(
        os.path.join(FRONTEND_DIR, "JS"),
        filename
    )


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.route("/health")
def health():
    return jsonify({
        "status": "ok"
    })


# --------------------------------------------------
# SOS SMS CONFIGURATION
# --------------------------------------------------

API_URL = "http://bulksmsbd.net/api/smsapi"

API_KEY = os.environ.get("BULKSMS_API_KEY")
SENDER_ID = os.environ.get("BULKSMS_SENDER_ID")
RECIPIENTS = os.environ.get("SOS_RECIPIENTS")


# --------------------------------------------------
# SEND SOS
# --------------------------------------------------

@app.route("/send-sos", methods=["POST"])
def send_sos():

    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip()
    message = str(data.get("message", "")).strip()

    latitude = data.get("latitude")
    longitude = data.get("longitude")

    # ----------------------------------------------
    # Validate name
    # ----------------------------------------------

    if not name:
        return jsonify({
            "success": False,
            "error": "Name is required."
        }), 400

    # ----------------------------------------------
    # Validate location
    # ----------------------------------------------

    if latitude is None or longitude is None:
        return jsonify({
            "success": False,
            "error": "Current location is not available."
        }), 400

    try:
        latitude = float(latitude)
        longitude = float(longitude)

    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "Invalid GPS coordinates."
        }), 400

    if not -90 <= latitude <= 90:
        return jsonify({
            "success": False,
            "error": "Invalid latitude."
        }), 400

    if not -180 <= longitude <= 180:
        return jsonify({
            "success": False,
            "error": "Invalid longitude."
        }), 400

    # ----------------------------------------------
    # Check SMS configuration
    # ----------------------------------------------

    if not API_KEY:
        return jsonify({
            "success": False,
            "error": "BulkSMSBD API key is not configured."
        }), 500

    if not SENDER_ID:
        return jsonify({
            "success": False,
            "error": "BulkSMSBD sender ID is not configured."
        }), 500

    if not RECIPIENTS:
        return jsonify({
            "success": False,
            "error": "SOS recipients are not configured."
        }), 500

    # ----------------------------------------------
    # Google Maps location
    # ----------------------------------------------

    map_url = (
        f"https://www.google.com/maps"
        f"?q={latitude},{longitude}"
    )

    # ----------------------------------------------
    # Build SOS message
    # ----------------------------------------------

    if message:

        sms_message = f"""SOS from
{name}

Message:
{message}

Location Map:
{map_url}"""

    else:

        sms_message = f"""SOS from
{name}

Location Map:
{map_url}"""

    # ----------------------------------------------
    # BulkSMSBD request
    # ----------------------------------------------

    payload = {
        "api_key": API_KEY,
        "senderid": SENDER_ID,
        "number": RECIPIENTS,
        "message": sms_message
    }

    try:

        response = requests.post(
            API_URL,
            data=payload,
            timeout=15
        )

        print(
            "BulkSMSBD HTTP status:",
            response.status_code
        )

        print(
            "BulkSMSBD response:",
            response.text
        )

        if response.ok:

            return jsonify({
                "success": True,
                "message": "SOS sent successfully."
            })

        return jsonify({
            "success": False,
            "error": "SMS service returned an error."
        }), 502

    except requests.exceptions.Timeout:

        return jsonify({
            "success": False,
            "error": "SMS service timed out. Please try again."
        }), 504

    except requests.exceptions.RequestException as e:

        print(
            "BulkSMSBD request failed:",
            str(e)
        )

        return jsonify({
            "success": False,
            "error": "Unable to connect to the SMS service."
        }), 500


# --------------------------------------------------
# RUN
# --------------------------------------------------

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 5000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
