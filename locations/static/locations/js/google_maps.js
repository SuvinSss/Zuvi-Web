/** Shared, lazy Google Maps loader and draggable location pin. */
(function () {
    "use strict";
    if (window.ZuuviMaps) return;

    var loading;
    var unavailable = "Google Maps is unavailable. You can still use your current location.";

    function config() {
        var el = document.getElementById("google-maps-config");
        return el ? JSON.parse(el.textContent) : {};
    }

    function load() {
        if (loading) return loading;
        var options = config();
        if (!options.apiKey || !options.mapId) {
            return Promise.reject(new Error(unavailable));
        }
        loading = new Promise(function (resolve, reject) {
            var timer = setTimeout(fail, 20000);
            function fail() {
                clearTimeout(timer);
                reject(new Error(unavailable));
            }
            window.gm_authFailure = function () {
                fail();
                window.dispatchEvent(new Event("zuuvi:maps-error"));
            };
            window.zuuviGoogleMapsReady = function () {
                clearTimeout(timer);
                resolve(window.google.maps);
            };
            var params = new URLSearchParams({
                key: options.apiKey,
                loading: "async",
                callback: "zuuviGoogleMapsReady",
                v: "weekly",
                libraries: "maps,marker",
            });
            var script = document.createElement("script");
            script.src = "https://maps.googleapis.com/maps/api/js?" + params.toString();
            script.async = true;
            script.onerror = fail;
            document.head.appendChild(script);
        });
        return loading;
    }

    function coordinates(lat, lng) {
        if (lat === null || lat === undefined || lng === null || lng === undefined ||
                String(lat).trim() === "" || String(lng).trim() === "") return null;
        lat = Number(lat);
        lng = Number(lng);
        return Number.isFinite(lat) && Number.isFinite(lng) &&
            lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180 ? {lat: lat, lng: lng} : null;
    }

    function createPicker(element, initial, onChange) {
        return load().then(function (maps) {
            var map = new maps.Map(element, {
                center: initial || {lat: 20.5937, lng: 78.9629},
                zoom: initial ? 16 : 5,
                mapId: config().mapId,
                streetViewControl: false,
                mapTypeControl: false,
                clickableIcons: false,
            });
            var marker;
            function select(position, focus, notify) {
                if (!position) return;
                if (!marker) {
                    marker = new maps.marker.AdvancedMarkerElement({
                        map: map,
                        position: position,
                        gmpDraggable: true,
                        title: "Selected location. Drag to adjust.",
                    });
                    marker.addEventListener("gmp-dragend", function () {
                        var point = marker.position;
                        select(coordinates(
                            typeof point.lat === "function" ? point.lat() : point.lat,
                            typeof point.lng === "function" ? point.lng() : point.lng
                        ));
                    });
                } else {
                    marker.position = position;
                }
                if (focus) {
                    map.panTo(position);
                    map.setZoom(16);
                }
                if (notify !== false) onChange(position);
            }
            map.addListener("click", function (event) {
                if (event.latLng) select(coordinates(event.latLng.lat(), event.latLng.lng()));
            });
            if (initial) select(initial, false, false);
            return {select: select, refresh: function () {
                maps.event.trigger(map, "resize");
                if (marker) map.panTo(marker.position);
            }};
        });
    }

    function addressDetails(position) {
        if (!position) return Promise.resolve(null);
        return load().then(function (maps) {
            return maps.importLibrary("geocoding");
        }).then(function (library) {
            return new Promise(function (resolve) {
                var timer = setTimeout(function () { resolve(null); }, 8000);
                new library.Geocoder().geocode({location: position}, function (results, status) {
                    clearTimeout(timer);
                    if (status !== "OK" || !results || !results.length) return resolve(null);
                    var result = results[0];
                    function component(type) {
                        var item = (result.address_components || []).find(function (part) {
                            return part.types.includes(type);
                        });
                        return item ? item.long_name : "";
                    }
                    resolve({
                        label: result.formatted_address || "",
                        line1: [component("street_number"), component("route")].filter(Boolean).join(" ") || component("sublocality_level_1"),
                        city: component("locality") || component("administrative_area_level_3"),
                        district: component("administrative_area_level_2"),
                        state: component("administrative_area_level_1"),
                        postal_code: component("postal_code"),
                    });
                });
            });
        }).catch(function () { return null; });
    }

    function reverseGeocode(position) {
        return addressDetails(position).then(function (details) { return details && details.label; });
    }

    function attachSearch(container, onSelect, onError) {
        if (!container || container.dataset.initialized) return Promise.resolve();
        container.dataset.initialized = "1";
        return load().then(function (maps) { return maps.importLibrary("places"); }).then(function (library) {
            var search = new library.PlaceAutocompleteElement();
            search.placeholder = "Search area, street or landmark";
            search.setAttribute("aria-label", "Search for a delivery location");
            search.addEventListener("gmp-error", function () { onError("Search is unavailable. Use your current location or choose on the map."); });
            var selection = 0;
            search.addEventListener("gmp-select", async function (event) {
                var current = ++selection;
                try {
                    var place = event.placePrediction.toPlace();
                    await place.fetchFields({fields: ["location", "formattedAddress"]});
                    if (current === selection && place.location) {
                        onSelect(coordinates(place.location.lat(), place.location.lng()), place.formattedAddress);
                    }
                } catch (error) { onError("Could not find this place. Try another search or use the map."); }
            });
            container.replaceChildren(search);
        }).catch(function () {
            container.textContent = "Search unavailable. You can still select a point below.";
        });
    }

    window.ZuuviMaps = {
        createPicker: createPicker,
        coordinates: coordinates,
        reverseGeocode: reverseGeocode,
        addressDetails: addressDetails,
        attachSearch: attachSearch,
        unavailable: unavailable,
    };
})();
