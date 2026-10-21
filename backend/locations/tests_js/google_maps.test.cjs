// Offline interaction checks: node --test locations/tests_js/google_maps.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(__dirname + '/../static/locations/js/google_maps.js', 'utf8');

function browser(config = {apiKey: 'test-key', mapId: 'test-map'}) {
    const scripts = [], maps = [], markers = [], events = [];
    class Map {
        constructor(el, options) { this.options = options; this.listeners = {}; maps.push(this); }
        addListener(name, fn) { this.listeners[name] = fn; }
        panTo(position) { this.center = position; }
        setZoom(zoom) { this.zoom = zoom; }
    }
    class Geocoder {
        geocode(request, callback) {
            callback([{formatted_address: '12 MG Road, Bengaluru, India'}], 'OK');
        }
    }
    class AdvancedMarkerElement {
        constructor(options) { Object.assign(this, options); this.listeners = {}; markers.push(this); }
        addListener(name, fn) { this.listeners[name] = fn; }
        addEventListener(name, fn) { this.listeners[name] = fn; }
    }
    const context = vm.createContext({
        URLSearchParams, Event, setTimeout, clearTimeout,
        window: {dispatchEvent: event => events.push(event.type)},
        document: {
            getElementById: () => ({textContent: JSON.stringify(config)}),
            createElement: () => ({}),
            head: {appendChild: script => scripts.push(script)},
        },
    });
    vm.runInContext(source, context);
    function ready() {
        context.window.google = {maps: {Map, Geocoder, marker: {AdvancedMarkerElement},
            importLibrary: async () => ({Geocoder})}};
        context.window.zuuviGoogleMapsReady();
    }
    return {api: context.window.ZuuviMaps, scripts, maps, markers, events, context, ready};
}

test('one API request supports separate pickers, click and drag update only their own selection', async () => {
    const b = browser(), first = [], second = [];
    const a = b.api.createPicker({}, null, p => first.push(p));
    const c = b.api.createPicker({}, null, p => second.push(p));
    assert.equal(b.scripts.length, 1);
    b.ready();
    await Promise.all([a, c]);
    b.maps[0].listeners.click({latLng: {lat: () => 12.345678, lng: () => 77.654321}});
    assert.equal(first[0].lat, 12.345678);
    assert.equal(second.length, 0);
    assert.equal(b.markers[0].gmpDraggable, true);
    b.markers[0].position = {lat: 13, lng: 78};
    b.markers[0].listeners['gmp-dragend']();
    assert.equal(first[1].lat, 13);
    assert.equal(b.markers.length, 1);
});

test('saved coordinates position the pin without overwriting newer form state', async () => {
    const b = browser(), changes = [];
    const result = b.api.createPicker({}, {lat: 0, lng: 0}, p => changes.push(p));
    b.ready();
    const picker = await result;
    assert.equal(b.maps[0].options.center.lat, 0);
    assert.equal(changes.length, 0);
    picker.select({lat: 10, lng: 20}, true);
    assert.equal(b.maps[0].center.lat, 10);
    assert.equal(b.maps[0].zoom, 16);
    assert.equal(changes[0].lng, 20);
});

test('empty, nonfinite and out-of-range coordinates do not become pins; zero is valid', () => {
    const b = browser();
    for (const pair of [['', ''], [null, 0], [91, 0], [0, 181], ['NaN', 0], [Infinity, 0]]) {
        assert.equal(b.api.coordinates(...pair), null);
    }
    assert.equal(b.api.coordinates('0', '0').lat, 0);
});

test('missing configuration avoids loading Google and reports an actionable error', async () => {
    for (const config of [{apiKey: '', mapId: 'map'}, {apiKey: 'key', mapId: ''}]) {
        const b = browser(config);
        await assert.rejects(b.api.createPicker({}, null, () => {}), /current location/);
        assert.equal(b.scripts.length, 0);
    }
});

test('reverse geocoding returns a place name for the selected point', async () => {
    const b = browser();
    const result = b.api.reverseGeocode({lat: 12.9716, lng: 77.5946});
    b.ready();
    assert.equal(await result, '12 MG Road, Bengaluru, India');
});

test('geocoding API rejection returns a fallback without breaking pin selection', async () => {
    const b = browser();
    const picker = b.api.createPicker({}, null, () => {});
    b.ready();
    await picker;
    b.context.window.google.maps.importLibrary = async () => { throw new Error('API unavailable'); };
    assert.equal(await b.api.reverseGeocode({lat: 12, lng: 77}), null);
    assert.equal(b.maps.length, 1);
});

test('network and authentication failures are handled', async () => {
    for (const failure of ['network', 'auth']) {
        const b = browser();
        const result = b.api.createPicker({}, null, () => {});
        if (failure === 'network') b.scripts[0].onerror();
        else b.context.window.gm_authFailure();
        await assert.rejects(result, /unavailable/);
        if (failure === 'auth') assert.deepEqual(b.events, ['zuuvi:maps-error']);
    }
});
