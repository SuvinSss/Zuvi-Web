/** Optional location selection. Browsing never requires a map or a saved point. */
(function () {
    "use strict";

    function init() {
        var modalEl = document.getElementById("deliveryLocationModal");
        if (!modalEl || typeof bootstrap === "undefined") return;

        var modal = new bootstrap.Modal(modalEl, { keyboard: true, backdrop: true });
        var errorEl = modalEl.querySelector("[data-location-gate-error]");
        var statusEl = modalEl.querySelector("[data-location-gate-status]");
        var currentBtn = modalEl.querySelector("[data-location-use-current]");
        var manualBtn = modalEl.querySelector("[data-location-toggle-manual]");
        var manualPanel = modalEl.querySelector("[data-location-manual-panel]");
        var confirmBtn = modalEl.querySelector("[data-location-confirm-manual]");
        var coordsDisplay = modalEl.querySelector("[data-location-gate-coords]");
        var mapEl = modalEl.querySelector("[data-location-gate-map]");
        var opener = null;
        var epoch = 0;
        var open = false;
        var pendingCoords = null;
        var map = null;
        var marker = null;
        var timer = null;
        var resources = null;
        var saving = false;

        function message(error, status) {
            errorEl.textContent = error || "";
            errorEl.classList.toggle("d-none", !error);
            statusEl.textContent = status || "";
        }

        function active(token) { return open && token === epoch; }

        function resetAttempt() {
            epoch += 1;
            clearTimeout(timer);
            pendingCoords = null;
            confirmBtn.disabled = true;
            currentBtn.disabled = saving;
            manualBtn.disabled = saving;
            if (map) map.remove();
            map = null;
            marker = null;
            manualPanel.classList.add("d-none");
            manualBtn.setAttribute("aria-expanded", "false");
            coordsDisplay.textContent = "Select an identifiable place on the map. The initial map centre is not a selection.";
            return epoch;
        }

        function validPoint(lat, lng) {
            return Number.isFinite(lat) && Number.isFinite(lng) &&
                lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180;
        }

        function savePoint(lat, lng, label, token) {
            if (!active(token) || saving) return;
            if (!validPoint(lat, lng)) {
                message("No valid location was returned. Retry or continue browsing.");
                return;
            }
            saving = true;
            currentBtn.disabled = manualBtn.disabled = confirmBtn.disabled = true;
            message("", "Saving your selected location…");
            var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
            var body = new URLSearchParams({ latitude: lat, longitude: lng, label: label });
            var controller = new AbortController();
            var saveTimer = setTimeout(function () { controller.abort(); }, 15000);
            fetch(window.ZOOP_LOCATION_SET_URL, {
                method: "POST",
                headers: {
                    "X-CSRFToken": match ? decodeURIComponent(match[1]) : "",
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                body: body.toString(),
                signal: controller.signal,
            }).then(function (response) {
                if (!response.ok) throw new Error("save failed");
                return response.json();
            }).then(function (data) {
                if (!active(token)) return;
                if (!data || !data.ok) throw new Error("save failed");
                document.querySelectorAll("[data-open-location-gate] strong").forEach(function (el) {
                    el.textContent = data.label;
                });
                modal.hide();
            }).catch(function () {
                if (active(token)) {
                    message("We could not confirm the save. You can continue browsing; reload to check your location before trying again.");
                }
            }).finally(function () {
                clearTimeout(saveTimer);
                saving = false;
                currentBtn.disabled = manualBtn.disabled = false;
                confirmBtn.disabled = !pendingCoords;
            });
        }

        // Load on demand: a failed or stalled CDN must never block page parsing.
        function loadMapResources() {
            if (resources) return resources;
            var nodes = [];
            resources = Promise.all([
                ["link", mapEl.dataset.mapCss, mapEl.dataset.mapCssIntegrity],
                ["script", mapEl.dataset.mapScript, mapEl.dataset.mapScriptIntegrity],
            ].map(function (spec) {
                return new Promise(function (resolve, reject) {
                    var node = document.createElement(spec[0]);
                    nodes.push(node);
                    var resourceTimer = setTimeout(function () { reject(new Error("Map loading timed out.")); }, 10000);
                    node.onload = function () { clearTimeout(resourceTimer); resolve(); };
                    node.onerror = function () { clearTimeout(resourceTimer); reject(new Error("Map resources are unavailable.")); };
                    node.integrity = spec[2];
                    node.crossOrigin = "";
                    if (spec[0] === "link") {
                        node.rel = "stylesheet";
                        node.href = spec[1];
                    } else {
                        node.async = true;
                        node.src = spec[1];
                    }
                    document.head.appendChild(node);
                });
            })).then(function () {
                if (typeof L === "undefined") throw new Error("The map library is unavailable.");
            }).catch(function (error) {
                nodes.forEach(function (node) { node.remove(); });
                resources = null;
                throw error;
            });
            return resources;
        }

        currentBtn.addEventListener("click", function () {
            var token = resetAttempt();
            message("");
            if (!navigator.geolocation) {
                message("Geolocation is unavailable. Try the map, your saved addresses, or continue browsing.");
                return;
            }
            currentBtn.disabled = true;
            message("", "Waiting for your location… You can continue browsing at any time.");
            var settled = false;
            function fail(code) {
                if (!active(token) || settled) return;
                settled = true;
                clearTimeout(timer);
                currentBtn.disabled = false;
                var reasons = {
                    1: "Location permission was denied.",
                    2: "Your current location is unavailable.",
                    3: "Finding your location timed out.",
                };
                message((reasons[code] || reasons[2]) + " Try again, use the map or saved addresses, or continue browsing.");
            }
            timer = setTimeout(function () { fail(3); }, 15000);
            try {
                navigator.geolocation.getCurrentPosition(function (position) {
                    if (!active(token) || settled) return;
                    settled = true;
                    clearTimeout(timer);
                    currentBtn.disabled = false;
                    savePoint(position.coords.latitude, position.coords.longitude, "Current location", token);
                }, function (error) { fail(error.code); }, {
                    enableHighAccuracy: true, timeout: 15000, maximumAge: 0,
                });
            } catch (error) { fail(2); }
        });

        manualBtn.addEventListener("click", function () {
            var token = resetAttempt();
            manualPanel.classList.remove("d-none");
            manualBtn.setAttribute("aria-expanded", "true");
            message("", "Loading map… If it is unusable, continue browsing or use your saved addresses.");
            loadMapResources().then(function () {
                if (!active(token)) return;
                var ready = false;
                var failed = false;
                function mapFailure(reason) {
                    if (!active(token)) return;
                    failed = true;
                    pendingCoords = null;
                    confirmBtn.disabled = true;
                    clearTimeout(timer);
                    message(reason + " Try Enter location manually again, use saved addresses, or continue browsing.");
                }
                try {
                    map = L.map(mapEl).setView([20.5937, 78.9629], 5);
                    var layer = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
                        maxZoom: 19,
                        referrerPolicy: "strict-origin",
                        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                    });
                    layer.on("tileerror", function () { mapFailure("The map could not load."); });
                    layer.on("tileload", function () {
                        if (!active(token) || failed) return;
                        ready = true;
                        clearTimeout(timer);
                        message("", "Only select a place you can identify. If the map is blocked or unclear, continue browsing instead.");
                    });
                    timer = setTimeout(function () { mapFailure("Map loading timed out."); }, 10000);
                    layer.addTo(map);
                    map.on("click", function (event) {
                        if (!active(token) || !ready || failed || saving) return;
                        var lat = event.latlng.lat;
                        var lng = event.latlng.lng;
                        if (!validPoint(lat, lng)) return;
                        pendingCoords = { lat: lat, lng: lng };
                        if (marker) marker.setLatLng(event.latlng);
                        else marker = L.marker(event.latlng).addTo(map);
                        coordsDisplay.textContent = "Selected pin: " + lat.toFixed(5) + ", " + lng.toFixed(5);
                        confirmBtn.disabled = false;
                    });
                    map.invalidateSize();
                } catch (error) { mapFailure("The map could not start."); }
            }).catch(function (error) {
                if (active(token)) message(error.message + " Retry, use saved addresses, or continue browsing.");
            });
        });

        confirmBtn.addEventListener("click", function () {
            if (pendingCoords) savePoint(pendingCoords.lat, pendingCoords.lng, "Pinned location", epoch);
        });
        modalEl.addEventListener("show.bs.modal", function () {
            open = true;
            resetAttempt();
            message("", saving ? "A previous save is still completing. You can continue browsing." : "");
        });
        modalEl.addEventListener("shown.bs.modal", function () {
            modalEl.querySelector("[data-location-close]").focus();
        });
        modalEl.addEventListener("hide.bs.modal", function () {
            open = false;
            resetAttempt();
        });
        modalEl.addEventListener("hidden.bs.modal", function () {
            if (opener && opener.isConnected) opener.focus();
        });
        document.querySelectorAll("[data-open-location-gate]").forEach(function (trigger) {
            trigger.addEventListener("click", function () {
                opener = trigger;
                modal.show();
            });
        });
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})();
