/**
 * Leaflet-based location picker.
 * Expects elements with [data-location-picker], data-lat-input-id, data-lng-input-id.
 */
(function () {
  "use strict";

  var DEFAULT_CENTER = [20.5937, 78.9629];
  var DEFAULT_ZOOM = 5;
  var SELECTED_ZOOM = 16;

  function fixLeafletIcons() {
    if (typeof L === "undefined" || L.Icon.Default.prototype._zoopFixed) {
      return;
    }
    delete L.Icon.Default.prototype._getIconUrl;
    L.Icon.Default.mergeOptions({
      iconRetinaUrl:
        "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/images/marker-icon-2x.png",
      iconUrl:
        "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/images/marker-icon.png",
      shadowUrl:
        "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/images/marker-shadow.png",
    });
    L.Icon.Default.prototype._zoopFixed = true;
  }

  function parseCoord(value) {
    if (value === null || value === undefined || String(value).trim() === "") {
      return null;
    }
    var n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function formatCoord(n) {
    return n.toFixed(6);
  }

  function initPicker(root) {
    var latId = root.getAttribute("data-lat-input-id");
    var lngId = root.getAttribute("data-lng-input-id");
    var latInput = document.getElementById(latId);
    var lngInput = document.getElementById(lngId);
    var mapEl = root.querySelector("[data-location-map]");
    var coordsDisplay = root.querySelector("[data-coords-display]");
    var errorEl = root.querySelector("[data-location-error]");
    var useBtn = root.querySelector("[data-use-location]");

    if (!latInput || !lngInput || !mapEl || typeof L === "undefined") {
      return;
    }

    fixLeafletIcons();

    var initialLat = parseCoord(latInput.value);
    var initialLng = parseCoord(lngInput.value);
    var hasInitial =
      initialLat !== null &&
      initialLng !== null &&
      initialLat >= -90 &&
      initialLat <= 90 &&
      initialLng >= -180 &&
      initialLng <= 180;

    var map = L.map(mapEl).setView(
      hasInitial ? [initialLat, initialLng] : DEFAULT_CENTER,
      hasInitial ? SELECTED_ZOOM : DEFAULT_ZOOM
    );

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);

    var marker = null;

    function showError(message) {
      if (!errorEl) {
        return;
      }
      if (message) {
        errorEl.textContent = message;
        errorEl.classList.remove("d-none");
      } else {
        errorEl.textContent = "";
        errorEl.classList.add("d-none");
      }
    }

    function updateDisplay(lat, lng) {
      if (!coordsDisplay) {
        return;
      }
      if (lat === null || lng === null) {
        coordsDisplay.textContent = "No location selected yet.";
        return;
      }
      coordsDisplay.textContent =
        "Selected: " + formatCoord(lat) + ", " + formatCoord(lng);
    }

    function setCoordinates(lat, lng, options) {
      options = options || {};
      latInput.value = formatCoord(lat);
      lngInput.value = formatCoord(lng);
      updateDisplay(lat, lng);
      showError("");

      if (marker) {
        marker.setLatLng([lat, lng]);
      } else {
        marker = L.marker([lat, lng], { draggable: true }).addTo(map);
        marker.on("dragend", function () {
          var pos = marker.getLatLng();
          setCoordinates(pos.lat, pos.lng, { pan: false, zoom: false });
        });
      }

      if (options.pan !== false) {
        map.panTo([lat, lng]);
      }
      if (options.zoom) {
        map.setZoom(SELECTED_ZOOM);
      }
    }

    if (hasInitial) {
      setCoordinates(initialLat, initialLng, { pan: false, zoom: false });
    } else {
      updateDisplay(null, null);
    }

    map.on("click", function (e) {
      setCoordinates(e.latlng.lat, e.latlng.lng, { pan: false, zoom: false });
    });

    if (useBtn) {
      useBtn.addEventListener("click", function () {
        showError("");
        if (!navigator.geolocation) {
          showError("Geolocation is not supported by this browser.");
          return;
        }
        useBtn.disabled = true;
        navigator.geolocation.getCurrentPosition(
          function (position) {
            useBtn.disabled = false;
            setCoordinates(
              position.coords.latitude,
              position.coords.longitude,
              { pan: true, zoom: true }
            );
          },
          function (err) {
            useBtn.disabled = false;
            if (err.code === 1) {
              showError(
                "Location permission denied. Click the map to set a point instead."
              );
            } else if (err.code === 2) {
              showError(
                "Location unavailable. Click the map to set a point instead."
              );
            } else {
              showError(
                "Could not get your location. Click the map to set a point instead."
              );
            }
          },
          { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
        );
      });
    }

    // Leaflet needs a size recalculation after layout in Bootstrap cards.
    setTimeout(function () {
      map.invalidateSize();
    }, 0);
  }

  function initAll() {
    if (typeof L === "undefined") {
      return;
    }
    document
      .querySelectorAll("[data-location-picker]")
      .forEach(function (root) {
        if (root.getAttribute("data-initialized") === "1") {
          return;
        }
        root.setAttribute("data-initialized", "1");
        initPicker(root);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})();
