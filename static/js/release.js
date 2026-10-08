(function () {
    'use strict';
    var focus = document.querySelector('[data-release-focus]');
    var errors = document.querySelector('.alert-danger, .errorlist');
    if (focus && !errors) {
        requestAnimationFrame(function () { focus.focus({preventScroll:true}); focus.scrollIntoView({block:'center',behavior:'instant'}); });
    }
    document.querySelectorAll('.bottom-navigation a').forEach(function (link) {
        var path = new URL(link.href, location.origin).pathname;
        if ((path === '/' && location.pathname === '/') || (path !== '/' && location.pathname.indexOf(path) === 0)) link.setAttribute('aria-current','page');
    });
    if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('/service-worker.js').catch(function () {});
    var pendingInstall;
    window.addEventListener('beforeinstallprompt', function (event) {
        event.preventDefault(); pendingInstall=event;
        document.querySelectorAll('[data-install-app]').forEach(function (button) { button.hidden=false; });
    });
    document.querySelectorAll('[data-install-app]').forEach(function (button) {
        button.addEventListener('click', async function () {
            if (!pendingInstall) return;
            await pendingInstall.prompt(); await pendingInstall.userChoice; pendingInstall=null; button.hidden=true;
        });
    });
})();
