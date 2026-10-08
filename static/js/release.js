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
    var dialog = document.querySelector('[data-install-dialog]');
    var installButtons = document.querySelectorAll('[data-install-app]');
    var nativeButton = document.querySelector('[data-install-native]');
    var standalone = window.matchMedia('(display-mode: standalone)');
    function isInstalled() { return standalone.matches || navigator.standalone === true; }
    function dismissed() {
        try { return sessionStorage.getItem('zuuvi-install-dismissed') === '1'; }
        catch (error) { return false; }
    }
    function dismiss() {
        try { sessionStorage.setItem('zuuvi-install-dismissed', '1'); } catch (error) {}
        if (dialog && dialog.open) dialog.close();
    }
    function openInstructions() {
        if (!dialog || isInstalled() || dialog.open || typeof dialog.showModal !== 'function') return;
        dialog.showModal();
    }
    function updateButtons() {
        installButtons.forEach(function (button) { button.hidden = isInstalled() || (!dialog && !pendingInstall); });
        if (nativeButton) nativeButton.hidden = !pendingInstall || isInstalled();
    }
    async function install() {
        if (!pendingInstall) { openInstructions(); return; }
        var prompt = pendingInstall;
        pendingInstall = null;
        updateButtons();
        try {
            await prompt.prompt();
            var choice = await prompt.userChoice;
            if (choice.outcome === 'accepted') dismiss();
        } catch (error) { openInstructions(); }
    }
    if (dialog) {
        var instructions = dialog.querySelector('[data-install-instructions]');
        var ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
        if (ios) instructions.textContent = 'In Safari, tap Share, then Add to Home Screen, then Add. If you opened ZuuVi inside another app, open this page in Safari first.';
        else if (/Android/.test(navigator.userAgent)) instructions.textContent = 'In Chrome, tap the three-dot menu, choose Install app or Add to Home screen, then confirm. If you opened ZuuVi inside another app, open this page in Chrome first.';
        else instructions.textContent = 'In Chrome or Edge, use the install icon in the address bar or the browser menu’s Install app option. In Safari on Mac, choose File → Add to Dock.';
        dialog.querySelectorAll('[data-install-dismiss]').forEach(function (button) { button.addEventListener('click', dismiss); });
        dialog.addEventListener('cancel', function (event) { event.preventDefault(); dismiss(); });
        if (dialog.hasAttribute('data-auto-open') && !dismissed() && !isInstalled()) {
            window.setTimeout(function () {
                if (!dismissed() && !document.querySelector('.modal.show, dialog[open]')) openInstructions();
            }, 600);
        }
    }
    window.addEventListener('beforeinstallprompt', function (event) {
        event.preventDefault(); pendingInstall = event; updateButtons();
    });
    window.addEventListener('appinstalled', function () {
        pendingInstall = null; dismiss();
        installButtons.forEach(function (button) { button.hidden = true; });
    });
    standalone.addEventListener('change', function () { if (isInstalled()) dismiss(); updateButtons(); });
    installButtons.forEach(function (button) {
        button.addEventListener('click', function () { if (dialog) openInstructions(); else install(); });
    });
    if (nativeButton) nativeButton.addEventListener('click', install);
    updateButtons();
})();
