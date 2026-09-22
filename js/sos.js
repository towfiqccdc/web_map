document.addEventListener("DOMContentLoaded", function () {

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
            "Location services are not supported by this browser.";

        updateSendButton();

        return;
    }


    locationStatus.textContent =
        "Getting your current location...";


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
                "Current location detected successfully.";


            locationMap.href = mapUrl;
            locationMap.style.display = "block";


            updatePreview();
        },


        function (error) {

            currentLatitude = null;
            currentLongitude = null;


            let errorMessage =
                "Unable to get your current location.";


            if (error.code === 1) {

                errorMessage =
                    "Location permission was denied. Please allow location access.";

            } else if (error.code === 2) {

                errorMessage =
                    "Your location could not be determined.";

            } else if (error.code === 3) {

                errorMessage =
                    "Location request timed out.";
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
                "Please enter your name.",
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
                "Your current location is not available.",
                "error"
            );

            return;
        }


        // Confirmation
        const confirmed = window.confirm(
            "Are you sure you want to send this SOS emergency message?"
        );


        if (!confirmed) {
            return;
        }


        // Disable button while sending
        sendButton.disabled = true;

        sendButton.textContent =
            "Sending SOS...";

        hideStatus();


        try {

            const response = await fetch(
                "/send-sos",
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
                    "The server returned an invalid response."
                );
            }


            if (
                response.ok &&
                result.success
            ) {

                showStatus(
                    "SOS sent successfully.",
                    "success"
                );

                sendButton.textContent =
                    "✓ SOS SENT";


            } else {

                throw new Error(
                    result.error ||
                    "Failed to send SOS."
                );
            }


        } catch (error) {

            console.error(
                "SOS error:",
                error
            );


            showStatus(
                error.message ||
                "Unable to send SOS. Please try again.",
                "error"
            );


            sendButton.textContent =
                "🆘 SEND SOS";


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
