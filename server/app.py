from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import os
import time
import threading

# ============================================================
# PATHS
# ============================================================
# This file lives in /server. The front-end files
# (index.html, sos.html, css/, js/) live one folder up,
# in the project root — so ROOT_DIR points there.
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

# static_folder=None: Flask must NOT serve the whole project root.
# (Previously static_folder=ROOT_DIR exposed server/app.py, .git/,
# requirements.txt, etc. to anyone.) Only the explicit routes in
# the FRONT-END PAGES section below are served.
app = Flask(
    __name__,
    static_folder=None
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

# Default is unchanged (http). To use HTTPS so the API key is
# encrypted in transit, set BULKSMS_API_URL on Render to
# https://bulksmsbd.net/api/smsapi and send a test SOS.
API_URL = os.environ.get("BULKSMS_API_URL", "http://bulksmsbd.net/api/smsapi")

API_KEY = os.environ.get("BULKSMS_API_KEY")
SENDER_ID = os.environ.get("BULKSMS_SENDER_ID")
RECIPIENTS = os.environ.get("SOS_RECIPIENTS")

# BulkSMSBD answers HTTP 200 even for failures (wrong key, no
# balance, ...) and reports the real result in a JSON
# "response_code". 202 = "SMS Submitted Successfully".
SMS_SUCCESS_CODES = {202}

# Input limits (match the maxlength values in sos.html)
MAX_NAME_LEN = 100
MAX_MESSAGE_LEN = 500


# ============================================================
# RATE LIMITING
# ============================================================
# /send-sos has no login, so without a limit anyone could call it
# in a loop and flood the recipients / use up SMS balance.
# In-memory, per worker process: good enough to stop casual abuse.
# Tune on Render with environment variables if needed.
#
#   SOS_LIMIT_PER_IP   max SOS per IP per window   (default 5)
#   SOS_LIMIT_GLOBAL   max SOS in total per window (default 30)
#   SOS_LIMIT_WINDOW   window in seconds           (default 600)
# ============================================================

LIMIT_PER_IP = int(os.environ.get("SOS_LIMIT_PER_IP", "5"))
LIMIT_GLOBAL = int(os.environ.get("SOS_LIMIT_GLOBAL", "30"))
LIMIT_WINDOW = int(os.environ.get("SOS_LIMIT_WINDOW", "600"))

_hits = {}
_all_hits = []
_hits_lock = threading.Lock()


def client_ip():
    # Behind Render's proxy the real client is the LAST entry that
    # the proxy appended to X-Forwarded-For (earlier entries can be
    # forged by the caller).
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.remote_addr or "unknown"


def rate_limited(ip):
    now = time.time()
    cutoff = now - LIMIT_WINDOW

    with _hits_lock:
        _all_hits[:] = [t for t in _all_hits if t > cutoff]
        ip_hits = [t for t in _hits.get(ip, []) if t > cutoff]

        if len(ip_hits) >= LIMIT_PER_IP or len(_all_hits) >= LIMIT_GLOBAL:
            _hits[ip] = ip_hits
            return True

        ip_hits.append(now)
        _hits[ip] = ip_hits
        _all_hits.append(now)

        # forget IPs with no recent activity
        for key in [k for k, v in _hits.items() if not v or v[-1] <= cutoff]:
            del _hits[key]

        return False


# ============================================================
# FRONT-END PAGES
# ============================================================
# Only these files are served: index.html, sos.html and the
# contents of css/ and js/. Nothing else in the repo is public.
# ============================================================

@app.route("/")
def index_page():
    return send_from_directory(ROOT_DIR, "index.html")


@app.route("/sos.html")
def sos_page():
    return send_from_directory(ROOT_DIR, "sos.html")


@app.route("/css/<path:filename>")
def css_files(filename):
    return send_from_directory(os.path.join(ROOT_DIR, "css"), filename)


@app.route("/js/<path:filename>")
def js_files(filename):
    return send_from_directory(os.path.join(ROOT_DIR, "js"), filename)


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

    # Limit length on the SERVER too (the maxlength in sos.html can
    # be bypassed), and collapse the name onto one line so it cannot
    # be used to fake extra lines in the SMS.
    name = " ".join(str(data.get("name", "")).split())[:MAX_NAME_LEN]
    message = str(data.get("message", "")).strip()[:MAX_MESSAGE_LEN]

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
    # RATE LIMIT (only counted when an SMS is actually about
    # to be sent)
    # --------------------------------------------------------

    if rate_limited(client_ip()):

        return jsonify({
            "success": False,
            "error": "Too many SOS requests. Please wait a few minutes, or call for help directly."
        }), 429


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

        # HTTP 200 alone is NOT proof the SMS was accepted: the
        # provider reports failures inside the JSON body.

        if response.ok:

            try:
                result = response.json()
                code = int(result.get("response_code"))
            except (ValueError, TypeError, AttributeError):
                code = None

            if code in SMS_SUCCESS_CODES:

                return jsonify({
                    "success": True,
                    "message": "SOS sent successfully."
                })

            print(
                "BulkSMSBD did not confirm delivery. response_code:",
                code
            )

            return jsonify({
                "success": False,
                "error": "SMS service did not accept the message. Please call for help directly."
            }), 502


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
