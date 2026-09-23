/** Connect a Google Maps pin to the form's hidden coordinate fields. */
(function () {
    "use strict";

    function initPicker(root) {
        if (root.dataset.initialized === "1") return;
        root.dataset.initialized = "1";
        var latInput = document.getElementById(root.dataset.latInputId);
        var lngInput = document.getElementById(root.dataset.lngInputId);
        var mapEl = root.querySelector("[data-location-map]");
        var display = root.querySelector("[data-coords-display]");
        var errorEl = root.querySelector("[data-location-error]");
        var useBtn = root.querySelector("[data-use-location]");
        if (!latInput || !lngInput || !mapEl) return;

        var picker;
        var selected;
        var revision = 0;
        var autofilled = {};
        function showError(message) {
            errorEl.textContent = message;
            errorEl.classList.toggle("d-none", !message);
        }
        function update(position) {
            var version = ++revision;
            selected = position;
            latInput.value = position.lat.toFixed(6);
            lngInput.value = position.lng.toFixed(6);
            display.textContent = "Selected: " + latInput.value + ", " + lngInput.value;
            [latInput, lngInput].forEach(function (input) {
                input.dispatchEvent(new Event("change", {bubbles: true}));
            });
            window.ZuuviMaps.addressDetails(position).then(function (details) {
                if (version !== revision || !details) return;
                display.textContent = details.label || display.textContent;
                if (root.dataset.autofillAddress !== "true") return;
                ["line1", "city", "district", "state", "postal_code"].forEach(function (name) {
                    var field = latInput.form.elements.namedItem(name);
                    // Preserve details the customer has typed or saved previously.
                    if (field && (!field.value || field.value === autofilled[name])) {
                        field.value = details[name] || "";
                        autofilled[name] = field.value;
                    }
                });
            });
        }
        if (!window.ZuuviMaps) {
            showError("Google Maps could not be initialized. Check the Maps API configuration.");
            return;
        }
        selected = window.ZuuviMaps.coordinates(latInput.value, lngInput.value);
        if (selected) update(selected);
        window.addEventListener("zuuvi:maps-error", function () {
            showError(window.ZuuviMaps.unavailable);
        });
        window.ZuuviMaps.createPicker(mapEl, selected, update).then(function (result) {
            picker = result;
            // Geolocation may have completed while the Maps API was loading.
            if (selected) picker.select(selected, true, false);
        }).catch(function () {
            showError(window.ZuuviMaps.unavailable);
        });
        window.ZuuviMaps.attachSearch(root.querySelector("[data-location-search]"), function (position) {
            if (picker) picker.select(position, true);
            else update(position);
        }, showError);

        useBtn.addEventListener("click", function () {
            showError("");
            if (!navigator.geolocation) {
                showError("Geolocation is not supported by this browser. Select a point on the map.");
                return;
            }
            useBtn.disabled = true;
            navigator.geolocation.getCurrentPosition(function (position) {
                useBtn.disabled = false;
                var point = window.ZuuviMaps.coordinates(position.coords.latitude, position.coords.longitude);
                if (!point) {
                    showError("Could not get your location. Select a point on the map.");
                    return;
                }
                if (picker) picker.select(point, true);
                else update(point);
            }, function () {
                useBtn.disabled = false;
                showError("Could not access your location. Allow location access or select a point on the map.");
            }, {enableHighAccuracy: true, timeout: 15000, maximumAge: 0});
        });
    }

    function init() {
        document.querySelectorAll("[data-location-picker]").forEach(initPicker);
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})();
