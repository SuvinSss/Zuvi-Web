const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(__dirname + '/../static/locations/js/location_gate.js', 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

function harness() {
    const nodes = new Map(), posts = [], lookups = [];
    let geoSuccess, geoError, onPin, reloaded = false;
    function node(name) {
        if (!nodes.has(name)) {
            const classes = new Set();
            nodes.set(name, {
                dataset: {}, listeners: {}, disabled: false, textContent: '', value: 'csrf-token',
                addEventListener(event, fn) { this.listeners[event] = fn; },
                classList: {add: c => classes.add(c), remove: c => classes.delete(c),
                    contains: c => classes.has(c), toggle(c, enabled) { enabled ? classes.add(c) : classes.delete(c); }},
            });
        }
        return nodes.get(name);
    }
    const root = node('root');
    root.dataset = {hasLocation: 'true', setUrl: '/location/set/', addUrl: '/customer/addresses/create/?from_location=1'};
    root.querySelector = node;
    const saved = node('saved');
    saved.dataset.savedAddressUrl = '/location/addresses/42/select/';
    root.querySelectorAll = selector => selector === '[data-saved-address-url]' ? [saved] : [saved, node('[data-location-use-current]')];
    const context = vm.createContext({
        URLSearchParams,
        bootstrap: {Modal: class { show() {} }},
        document: {
            readyState: 'complete', querySelectorAll: () => [], querySelector: () => null,
            getElementById: id => id === 'deliveryLocationModal' ? root : {textContent: 'null'},
        },
        navigator: {geolocation: {getCurrentPosition(success, error) { geoSuccess = success; geoError = error; }}},
        fetch: async (url, options) => { posts.push({url, options}); return {ok: true, json: async () => ({ok:true})}; },
        window: {
            addEventListener() {},
            location: {pathname: '/', search: '', reload() { reloaded = true; }, assign() {}},
            ZuuviMaps: {
                coordinates: (lat, lng) => lat == null || lng == null ? null : {lat:Number(lat), lng:Number(lng)},
                reverseGeocode: () => new Promise(resolve => lookups.push(resolve)),
                createPicker: async (el, initial, callback) => { onPin = callback; return {select() {}, refresh() {}}; },
                attachSearch() {},
            },
        },
    });
    vm.runInContext(source, context);
    return {node, posts, lookups, context, saved,
        click: selector => node(selector).listeners.click(),
        locate: (lat, lng) => geoSuccess({coords:{latitude:lat, longitude:lng}}),
        deny: () => geoError({code:1}),
        pin: p => onPin(p), reloaded: () => reloaded};
}

test('current location is reviewed before any POST, then confirms name and six-decimal coordinates', async () => {
    const h = harness();
    h.click('[data-location-use-current]');
    h.locate(12.123456789, 77.123456789);
    await flush();
    assert.equal(h.posts.length, 0);
    assert.equal(h.node('[data-location-confirm-manual]').disabled, true);
    h.lookups[0]('Bengaluru');
    await flush();
    assert.equal(h.node('[data-location-confirm-manual]').disabled, false);
    h.click('[data-location-confirm-manual]');
    await flush();
    const body = new URLSearchParams(h.posts[0].options.body);
    assert.equal(body.get('latitude'), '12.123457');
    assert.equal(body.get('label'), 'Bengaluru');
    assert.equal(h.posts[0].options.headers['X-CSRFToken'], 'csrf-token');
    assert.equal(h.reloaded(), true);
});

test('late reverse-geocoding responses cannot replace the latest pin label', async () => {
    const h = harness();
    h.click('[data-location-toggle-manual]');
    await flush();
    h.pin({lat:10,lng:20});
    h.pin({lat:11,lng:21});
    h.lookups[1]('Newest place');
    await flush();
    h.lookups[0]('Old place');
    await flush();
    assert.equal(h.node('[data-location-gate-coords]').textContent, 'Newest place');
});

test('denied geolocation keeps manual selection usable and does not submit', () => {
    const h = harness();
    h.click('[data-location-use-current]');
    h.deny();
    assert.match(h.node('[data-location-gate-error]').textContent, /Location access is off/);
    assert.equal(h.node('[data-location-use-current]').disabled, false);
    assert.equal(h.posts.length, 0);
});

test('current location still confirms when map and address lookup are unavailable', async () => {
    const h = harness();
    h.context.window.ZuuviMaps.createPicker = async () => { throw new Error('map unavailable'); };
    h.click('[data-location-use-current]');
    h.locate(12, 77);
    h.lookups[0](null);
    await flush();
    assert.equal(h.node('[data-location-confirm-manual]').disabled, false);
    assert.match(h.node('[data-location-gate-error]').textContent, /map could not load/);
    h.click('[data-location-confirm-manual]');
    await flush();
    assert.equal(new URLSearchParams(h.posts[0].options.body).get('label'), 'Pinned location');
});

test('failed saves keep the selector open and allow another attempt', async () => {
    const h = harness();
    h.context.fetch = async () => ({ok:false, json:async () => ({error:'Try again'})});
    h.click('[data-location-use-current]');
    h.locate(12, 77);
    h.lookups[0]('Bengaluru');
    await flush();
    h.click('[data-location-confirm-manual]');
    await flush();
    assert.equal(h.reloaded(), false);
    assert.equal(h.node('[data-location-confirm-manual]').disabled, false);
    assert.match(h.node('[data-location-gate-error]').textContent, /Try again/);
});

test('saved address selection posts the owned-address route without trusting browser coordinates', async () => {
    const h = harness();
    h.saved.listeners.click();
    await flush();
    assert.equal(h.posts[0].url, '/location/addresses/42/select/');
    assert.equal(new URLSearchParams(h.posts[0].options.body).has('latitude'), false);
});
