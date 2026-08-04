/**
 * Blinkit-style "select your delivery location" gate.
 * Shows a modal on first visit until a location is stored in the session,
 * via geolocation or a manual map pin drop.
 */
(function () {
    "use strict";

    function getCsrfToken() {
        var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function postLocation(latitude, longitude, label) {
        var body = new URLSearchParams();
        body.set("latitude", latitude);
        body.set("longitude", longitude);
        body.set("label", label || "");
        body.set("next", window.location.pathname + window.location.search);

        return fetch(window.ZOOP_LOCATION_SET_URL, {
            method: "POST",
            headers: {
                "X-CSRFToken": getCsrfToken(),
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body: body.toString(),
        }).then(function (response) {
            return response.json();
        });
    }

    function init() {
        var modalEl = document.getElementById("deliveryLocationModal");
        if (!modalEl || typeof bootstrap === "undefined") {
            return;
        }

        var modal = new bootstrap.Modal(modalEl);
        var errorEl = modalEl.querySelector("[data-location-gate-error]");
        var useCurrentBtn = modalEl.querySelector("[data-location-use-current]");
        var toggleManualBtn = modalEl.querySelector("[data-location-toggle-manual]");
        var manualPanel = modalEl.querySelector("[data-location-manual-panel]");
        var confirmManualBtn = modalEl.querySelector("[data-location-confirm-manual]");
        var coordsDisplay = modalEl.querySelector("[data-location-gate-coords]");
        var mapEl = modalEl.querySelector("[data-location-gate-map]");

        var pendingCoords = null;
        var map = null;
        var marker = null;

        function showError(message) {
            if (!errorEl) return;
            if (message) {
                errorEl.textContent = message;
                errorEl.classList.remove("d-none");
            } else {
                errorEl.textContent = "";
                errorEl.classList.add("d-none");
            }
        }

        function finish(latitude, longitude, label) {
            postLocation(latitude, longitude, label).then(function (data) {
                if (data && data.ok) {
                    window.location.reload();
                } else {
                    showError((data && data.error) || "Could not save this location. Try again.");
                }
            }).catch(function () {
                showError("Could not save this location. Try again.");
            });
        }

        if (useCurrentBtn) {
            useCurrentBtn.addEventListener("click", function () {
                showError("");
                if (!navigator.geolocation) {
                    showError("Geolocation is not supported by this browser. Try entering it manually.");
                    return;
                }
                useCurrentBtn.disabled = true;
                navigator.geolocation.getCurrentPosition(
                    function (position) {
                        useCurrentBtn.disabled = false;
                        finish(position.coords.latitude, position.coords.longitude, "Current location");
                    },
                    function () {
                        useCurrentBtn.disabled = false;
                        showError("Location permission denied. Try entering it manually instead.");
                    },
                    { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
                );
            });
        }

        if (toggleManualBtn && manualPanel) {
            toggleManualBtn.addEventListener("click", function () {
                manualPanel.classList.toggle("d-none");
                if (!manualPanel.classList.contains("d-none") && !map && typeof L !== "undefined") {
                    map = L.map(mapEl).setView([20.5937, 78.9629], 5);
                    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                        maxZoom: 19,
                        attribution: '&copy; OpenStreetMap contributors',
                    }).addTo(map);
                    map.on("click", function (e) {
                        pendingCoords = { lat: e.latlng.lat, lng: e.latlng.lng };
                        if (marker) {
                            marker.setLatLng(e.latlng);
                        } else {
                            marker = L.marker(e.latlng).addTo(map);
                        }
                        coordsDisplay.textContent =
                            "Pin set: " + e.latlng.lat.toFixed(5) + ", " + e.latlng.lng.toFixed(5);
                        confirmManualBtn.disabled = false;
                    });
                    setTimeout(function () {
                        map.invalidateSize();
                    }, 0);
                }
            });
        }

        if (confirmManualBtn) {
            confirmManualBtn.addEventListener("click", function () {
                if (!pendingCoords) return;
                showError("");
                finish(pendingCoords.lat, pendingCoords.lng, "Pinned location");
            });
        }

        document.querySelectorAll("[data-open-location-gate]").forEach(function (trigger) {
            trigger.addEventListener("click", function () {
                modal.show();
            });
        });

        if (!window.ZOOP_HAS_DELIVERY_LOCATION) {
            modal.show();
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
