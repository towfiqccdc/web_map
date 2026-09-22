document.addEventListener("DOMContentLoaded", function () {

// ==================================================
// BACKEND API BASE
// ==================================================
// This page is hosted on GitHub Pages, which only serves
// static files. The actual SOS-sending backend (Flask +
// BulkSMSBD) runs separately on Render, so requests must
// go to its full URL instead of a relative path.
// ==================================================

const API_BASE = "https://web-map-a44c.onrender.com";

const nameInput = document.getElementById("name");
const messageInput = document.getElementById("message");

const locationStatus = document.getElementById("locationStatus");
const locationMap = document.getElementById("locationMap");

const sendButton = document.getElementById("sendSOS");
const statusMessage = document.getElementById("statusMessage");

let currentLatitude = null;
let currentLongitude = null;


// ==================================================
// UPDATE SEND-READY STATE
// ==================================================
// (Renamed from updatePreview — there's no SMS preview
// panel anymore, this just re-checks whether the send
// button should be enabled.)

function updatePreview() {
    updateSendButton();
}


// ==================================================
// UPDATE SEND BUTTON
// ==================================================

function updateSendButton() {

    const hasName =
        nameInput.value.trim() !== "";

    const hasLocation =
        currentLatitude !== null &&
        currentLongitude !== null;

    sendButton.disabled =
        !(hasName && hasLocation);
}


// ==================================================
// GET CURRENT LOCATION
// ==================================================

function getCurrentLocation() {

    if (!navigator.geolocation) {

        locationStatus.textContent =
            "Location services are not supported by this browser. 此浏览器不支持定位功能。";

        updateSendButton();

        return;
    }


    locationStatus.textContent =
        "Getting your current location... 正在获取您的位置…";


    navigator.geolocation.getCurrentPosition(

        function (position) {

            currentLatitude =
                position.coords.latitude;

            currentLongitude =
                position.coords.longitude;


            const mapUrl =
                "https://www.google.com/maps?q=" +
                currentLatitude +
                "," +
                currentLongitude;


            locationStatus.textContent =
                "Current location detected successfully. 已成功获取当前位置。";


            locationMap.href = mapUrl;
            locationMap.style.display = "block";


            updatePreview();
        },


        function (error) {

            currentLatitude = null;
            currentLongitude = null;


            let errorMessage =
                "Unable to get your current location. 无法获取您的当前位置。";


            if (error.code === 1) {

                errorMessage =
                    "Location permission was denied. Please allow location access. 位置权限被拒绝，请允许访问位置信息。";

            } else if (error.code === 2) {

                errorMessage =
                    "Your location could not be determined. 无法确定您的位置。";

            } else if (error.code === 3) {

                errorMessage =
                    "Location request timed out. 获取位置超时。";
            }


            locationStatus.textContent =
                errorMessage;


            updatePreview();
        },


        {
            enableHighAccuracy: true,
            timeout: 15000,
            maximumAge: 0
        }
    );
}


// ==================================================
// INPUT EVENTS
// ==================================================

nameInput.addEventListener(
    "input",
    updatePreview
);

messageInput.addEventListener(
    "input",
    updatePreview
);


// ==================================================
// SEND SOS
// ==================================================

sendButton.addEventListener(
    "click",
    async function () {

        const name =
            nameInput.value.trim();

        const message =
            messageInput.value.trim();


        // Check name
        if (name === "") {

            showStatus(
                "Please enter your name. 请输入您的姓名。",
                "error"
            );

            nameInput.focus();

            return;
        }


        // Check location
        if (
            currentLatitude === null ||
            currentLongitude === null
        ) {

            showStatus(
                "Your current location is not available. 无法获取您的当前位置。",
                "error"
            );

            return;
        }


        // Confirmation
        const confirmed = window.confirm(
            "Are you sure you want to send this SOS emergency message?\n您确定要发送此紧急求救信息吗？"
        );


        if (!confirmed) {
            return;
        }


        // Disable button while sending
        sendButton.disabled = true;

        sendButton.textContent =
            "Sending SOS... 正在发送…";

        hideStatus();


        try {

            const response = await fetch(
                `${API_BASE}/send-sos`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({

                        name: name,

                        message: message,

                        latitude:
                            currentLatitude,

                        longitude:
                            currentLongitude
                    })
                }
            );


            let result;


            try {

                result = await response.json();

            } catch (jsonError) {

                throw new Error(
                    "The server returned an invalid response. 服务器返回了无效的响应。"
                );
            }


            if (
                response.ok &&
                result.success
            ) {

                showStatus(
                    "SOS sent successfully. 求救信息已成功发送。",
                    "success"
                );

                sendButton.textContent =
                    "✓ SOS SENT 已发送";


            } else {

                throw new Error(
                    result.error ||
                    "Failed to send SOS. 发送求救信息失败。"
                );
            }


        } catch (error) {

            console.error(
                "SOS error:",
                error
            );


            showStatus(
                error.message ||
                "Unable to send SOS. Please try again. 发送失败，请重试。",
                "error"
            );


            sendButton.textContent =
                "🆘 SEND SOS 发送求救";


            updateSendButton();
        }
    }
);


// ==================================================
// SHOW STATUS
// ==================================================

function showStatus(message, type) {

    statusMessage.textContent =
        message;

    statusMessage.className =
        "status-message";


    if (type === "success") {

        statusMessage.classList.add(
            "status-success"
        );

    } else {

        statusMessage.classList.add(
            "status-error"
        );
    }
}


// ==================================================
// HIDE STATUS
// ==================================================

function hideStatus() {

    statusMessage.textContent = "";

    statusMessage.className =
        "status-message";
}


// ==================================================
// INITIALIZE
// ==================================================

updatePreview();

getCurrentLocation();

});
