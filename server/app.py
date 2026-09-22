from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import os

# ============================================================
# PATHS
# ============================================================
# This file lives in /server. The front-end files
# (index.html, sos.html, css/, js/) live one folder up,
# in the project root — so ROOT_DIR points there.
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

app = Flask(
    __name__,
    static_folder=ROOT_DIR,
    static_url_path=""
)


# ============================================================
# CORS
# ============================================================
# The front end is hosted separately on GitHub Pages
# (a different origin from this Render backend), so the
# browser blocks the fetch("/send-sos") call unless this
# server explicitly allows that origin.
#
# Only the /send-sos endpoint needs this — the page routes
# above don't need CORS since browsers load them directly,
# not via fetch from another origin.
#
# Add any other frontend origins you use (e.g. a local dev
# server) to this list as needed.
# ============================================================

ALLOWED_ORIGINS = [
    "https://towfiqccdc.github.io",
]

CORS(
    app,
    resources={r"/send-sos": {"origins": ALLOWED_ORIGINS}}
)


# ============================================================
# BULKSMSBD CONFIGURATION
# ============================================================
# These values are supplied by Render Environment Variables.
#
# Render:
#   BULKSMS_API_KEY
#   BULKSMS_SENDER_ID
#   SOS_RECIPIENTS
#
# Do NOT put the actual API key directly in this file.
# ============================================================

API_URL = "http://bulksmsbd.net/api/smsapi"

API_KEY = os.environ.get("BULKSMS_API_KEY")
SENDER_ID = os.environ.get("BULKSMS_SENDER_ID")
RECIPIENTS = os.environ.get("SOS_RECIPIENTS")


# ============================================================
# FRONT-END PAGES
# ============================================================
# These serve index.html and sos.html directly. Everything
# else (css/style.css, js/app.js, js/sos.js, js/data.js) is
# picked up automatically by Flask's static handler because
# static_folder=ROOT_DIR and static_url_path="" above.
# ============================================================

@app.route("/")
def index_page():
    return send_from_directory(ROOT_DIR, "index.html")


@app.route("/sos.html")
def sos_page():
    return send_from_directory(ROOT_DIR, "sos.html")


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():
    return jsonify({
        "status": "ok"
    })


# ============================================================
# SEND SOS
# ============================================================

@app.route("/send-sos", methods=["POST"])
def send_sos():

    # --------------------------------------------------------
    # Get JSON sent from sos.js
    # --------------------------------------------------------

    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip()
    message = str(data.get("message", "")).strip()

    latitude = data.get("latitude")
    longitude = data.get("longitude")


    # --------------------------------------------------------
    # NAME IS REQUIRED
    # --------------------------------------------------------

    if not name:
        return jsonify({
            "success": False,
            "error": "Name is required."
        }), 400


    # --------------------------------------------------------
    # LOCATION IS REQUIRED
    # --------------------------------------------------------

    if latitude is None or longitude is None:
        return jsonify({
            "success": False,
            "error": "Current location is not available."
        }), 400


    # --------------------------------------------------------
    # CHECK RENDER ENVIRONMENT VARIABLES
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # VALIDATE GPS COORDINATES
    # --------------------------------------------------------

    try:
        latitude = float(latitude)
        longitude = float(longitude)

    except (TypeError, ValueError):

        return jsonify({
            "success": False,
            "error": "Invalid GPS coordinates."
        }), 400


    # Latitude must be between -90 and 90
    if not -90 <= latitude <= 90:

        return jsonify({
            "success": False,
            "error": "Invalid latitude."
        }), 400


    # Longitude must be between -180 and 180
    if not -180 <= longitude <= 180:

        return jsonify({
            "success": False,
            "error": "Invalid longitude."
        }), 400


    # --------------------------------------------------------
    # CREATE GOOGLE MAPS LOCATION
    # --------------------------------------------------------

    map_url = (
        f"https://www.google.com/maps"
        f"?q={latitude},{longitude}"
    )


    # --------------------------------------------------------
    # CREATE SMS MESSAGE
    # --------------------------------------------------------
    #
    # MESSAGE IS OPTIONAL.
    #
    # With message:
    #
    # SOS from
    # John
    #
    # Message:
    # I need help.
    #
    # Location Map:
    # https://www.google.com/maps?q=...
    #
    #
    # Without message:
    #
    # SOS from
    # John
    #
    # Location Map:
    # https://www.google.com/maps?q=...
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # BULKSMSBD PAYLOAD
    # --------------------------------------------------------

    payload = {
        "api_key": API_KEY,
        "senderid": SENDER_ID,
        "number": RECIPIENTS,
        "message": sms_message
    }


    # --------------------------------------------------------
    # SEND SMS
    # --------------------------------------------------------

    try:

        response = requests.post(
            API_URL,
            data=payload,
            timeout=15
        )


        # ----------------------------------------------------
        # RENDER LOG
        # ----------------------------------------------------

        print(
            "BulkSMSBD HTTP status:",
            response.status_code
        )

        print(
            "BulkSMSBD response:",
            response.text
        )


        # ----------------------------------------------------
        # CHECK HTTP STATUS
        # ----------------------------------------------------

        if response.ok:

            return jsonify({
                "success": True,
                "message": "SOS sent successfully."
            })


        return jsonify({
            "success": False,
            "error": "SMS service returned an error."
        }), 502


    # --------------------------------------------------------
    # TIMEOUT
    # --------------------------------------------------------

    except requests.exceptions.Timeout:

        print("BulkSMSBD request timed out.")

        return jsonify({
            "success": False,
            "error": "SMS service timed out. Please try again."
        }), 504


    # --------------------------------------------------------
    # CONNECTION ERROR
    # --------------------------------------------------------

    except requests.exceptions.RequestException as e:

        print(
            "BulkSMSBD request failed:",
            str(e)
        )

        return jsonify({
            "success": False,
            "error": "Unable to connect to the SMS service."
        }), 500


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 5000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
