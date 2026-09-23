/** Delivery address selector: choose, review the pin, then confirm. */
(function () {
    "use strict";
    function init() {
        var root = document.getElementById("deliveryLocationModal");
        if (!root || typeof bootstrap === "undefined") return;
        var modal = new bootstrap.Modal(root);
        var choose = root.querySelector("[data-location-choose]");
        var panel = root.querySelector("[data-location-manual-panel]");
        var error = root.querySelector("[data-location-gate-error]");
        var status = root.querySelector("[data-location-status]");
        var summary = root.querySelector("[data-location-gate-coords]");
        var confirm = root.querySelector("[data-location-confirm-manual]");
        var save = root.querySelector("[data-location-save-address]");
        var current = root.querySelector("[data-location-use-current]");
        var selected = JSON.parse(document.getElementById("selected-delivery-location").textContent) || {};
        var point = window.ZuuviMaps.coordinates(selected.latitude, selected.longitude);
        var label = selected.label || "";
        var picker, mapPromise, generation = 0, busy = false, locating = false, resolving = false;
        function showError(message) {
            error.textContent = message;
            error.classList.toggle("d-none", !message);
        }
        function buttons() {
            confirm.disabled = busy || resolving || !point;
            if (save) save.disabled = busy || resolving || !point;
            root.querySelectorAll("[data-saved-address-url], [data-location-use-current], [data-location-toggle-manual], [data-location-back]").forEach(function (button) {
                button.disabled = busy || locating;
            });
        }
        function update(position, knownLabel) {
            point = position;
            label = knownLabel || "";
            var version = ++generation;
            resolving = !knownLabel;
            buttons();
            summary.textContent = label || "Finding the address…";
            if (!knownLabel) window.ZuuviMaps.reverseGeocode(position).then(function (name) {
                if (version !== generation) return;
                label = name || "Pinned location";
                summary.textContent = name || "Location selected. Confirm this pin or add address details.";
                resolving = false;
                buttons();
            });
        }
        function showMap(position, knownLabel) {
            showError("");
            choose.classList.add("d-none");
            panel.classList.remove("d-none");
            if (position) update(position, knownLabel);
            else if (point) summary.textContent = label || "Review your selected pin.";
            if (!mapPromise) {
                mapPromise = window.ZuuviMaps.createPicker(root.querySelector("[data-location-gate-map]"), point, function (p) { update(p); })
                    .then(function (result) {
                        picker = result;
                        if (point) picker.select(point, true, false);
                        return result;
                    }).catch(function () {
                        showError("The map could not load. You can still confirm a location found by your device, or choose a saved address.");
                        mapPromise = null;
                    });
            } else if (picker) {
                picker.refresh();
                if (point) picker.select(point, true, false);
            }
            buttons();
        }
        function post(url, data) {
            data.set("next", window.location.pathname + window.location.search);
            return fetch(url, {
                method: "POST",
                headers: {
                    "X-CSRFToken": root.querySelector("[name=csrfmiddlewaretoken]").value,
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                body: data.toString(),
            }).then(async function (response) {
                var result = await response.json();
                if (!response.ok || !result.ok) throw new Error(result.error || "Could not save this location. Please try again.");
                return result;
            });
        }
        function finish(addAddress) {
            if (!point || busy) return;
            busy = true;
            buttons();
            showError("");
            status.textContent = "Saving your location…";
            post(root.dataset.setUrl, new URLSearchParams({
                latitude: point.lat.toFixed(6), longitude: point.lng.toFixed(6),
                label: label || "Pinned location",
            })).then(function () {
                if (addAddress) window.location.assign(root.dataset.addUrl);
                else window.location.reload();
            }).catch(function (reason) {
                showError(reason.message);
                busy = false;
                buttons();
                status.textContent = "";
            });
        }
        confirm.addEventListener("click", function () { finish(false); });
        if (save) save.addEventListener("click", function () { finish(true); });
        root.querySelector("[data-location-toggle-manual]").addEventListener("click", function () { showMap(); });
        root.querySelector("[data-location-back]").addEventListener("click", function () {
            panel.classList.add("d-none");
            choose.classList.remove("d-none");
            showError("");
        });
        current.addEventListener("click", function () {
            if (!navigator.geolocation) return showError("Your browser cannot find your location. Search or choose a point on the map.");
            locating = true;
            buttons();
            showError("");
            status.textContent = "Finding your current location…";
            navigator.geolocation.getCurrentPosition(function (position) {
                locating = false;
                status.textContent = "";
                showMap(window.ZuuviMaps.coordinates(position.coords.latitude, position.coords.longitude));
                buttons();
            }, function (reason) {
                locating = false;
                buttons();
                status.textContent = "";
                showError(reason.code === 1
                    ? "Location access is off. Allow it in your browser, search for an area, or select manually."
                    : "We couldn’t find your location. Try again, search for an area, or select manually.");
            }, {enableHighAccuracy: true, timeout: 15000, maximumAge: 0});
        });
        root.querySelectorAll("[data-saved-address-url]").forEach(function (button) {
            button.addEventListener("click", function () {
                if (busy) return;
                busy = true;
                buttons();
                status.textContent = "Selecting your address…";
                post(button.dataset.savedAddressUrl, new URLSearchParams()).then(function () {
                    window.location.reload();
                }).catch(function () {
                    busy = false;
                    buttons();
                    status.textContent = "";
                    showError("This address could not be selected. Please refresh and try again.");
                });
            });
        });
        root.addEventListener("shown.bs.modal", function () {
            window.ZuuviMaps.attachSearch(root.querySelector("[data-location-search]"), showMap, showError);
            if (picker && !panel.classList.contains("d-none")) picker.refresh();
        });
        document.querySelectorAll("[data-open-location-gate]").forEach(function (button) {
            button.addEventListener("click", function () { modal.show(); });
        });
        window.addEventListener("zuuvi:maps-error", function () { showError(window.ZuuviMaps.unavailable); });
        // Do not interrupt a customer's address-entry flow with a second picker.
        if (root.dataset.hasLocation !== "true" && !document.querySelector("[data-location-picker]") &&
                !window.location.pathname.startsWith("/customer/")) modal.show();
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})();
