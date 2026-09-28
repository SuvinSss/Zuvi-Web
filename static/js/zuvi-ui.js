/* Progressive enhancements only; server permissions and form POSTs remain authoritative. */
(function () {
    'use strict';
    document.querySelectorAll('.bi').forEach(function (icon) { icon.setAttribute('aria-hidden', 'true'); });
    document.querySelectorAll('[data-gallery-src]').forEach(function (button) {
        button.addEventListener('click', function () {
            var image = document.getElementById('product-gallery-main');
            if (!image) return;
            image.src = button.dataset.gallerySrc;
            image.alt = button.dataset.galleryAlt;
            document.querySelectorAll('[data-gallery-src]').forEach(function (item) {
                item.setAttribute('aria-pressed', String(item === button));
            });
        });
    });
    var path = window.location.pathname;
    document.querySelectorAll('.navbar-nav .nav-link, .account-nav a').forEach(function (link) {
        var target = new URL(link.href).pathname;
        if (path === target || (!target.endsWith('/dashboard/') && path.startsWith(target))) {
            link.setAttribute('aria-current', 'page');
        }
    });
    document.querySelectorAll('.table-responsive').forEach(function (region) {
        if (region.scrollWidth > region.clientWidth) {
            region.tabIndex = 0;
            region.setAttribute('role', 'region');
            region.setAttribute('aria-label', 'Scrollable table');
        }
    });
    document.querySelectorAll('.alert-danger, .errorlist').forEach(function (error) {
        error.setAttribute('role', 'alert');
    });
})();
