/**
 * Reload-free cart interactions: add-to-cart, quantity steppers, the
 * mini-cart drawer and the customer-page badge. Every endpoint this talks to
 * still works as a plain form POST + redirect when this script fails to
 * load — see the `.product-add-form` fallback and the server-side
 * `_is_ajax` branches in cart/views.py.
 */
(function () {
    "use strict";

    function getCsrfToken() {
        var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function formatQty(value) {
        var num = parseFloat(value);
        if (isNaN(num)) return value;
        return String(Math.round(num * 1000) / 1000);
    }

    function mutateCart(url, params) {
        return fetch(url, {
            method: "POST",
            headers: {
                "X-CSRFToken": getCsrfToken(),
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body: params.toString(),
        }).then(function (response) {
            return response.json().then(function (data) {
                return { status: response.status, data: data };
            });
        });
    }

    function formDataToParams(form) {
        var params = new URLSearchParams();
        new FormData(form).forEach(function (value, key) {
            params.append(key, value);
        });
        return params;
    }

    function showToast(message) {
        if (!message) return;
        var container = document.getElementById("zoopToastContainer");
        if (!container) {
            container = document.createElement("div");
            container.id = "zoopToastContainer";
            container.className = "zoop-toast-container";
            document.body.appendChild(container);
        }
        var toast = document.createElement("div");
        toast.className = "zoop-toast";
        toast.textContent = message;
        container.appendChild(toast);
        requestAnimationFrame(function () {
            toast.classList.add("is-visible");
        });
        setTimeout(function () {
            toast.classList.remove("is-visible");
            setTimeout(function () {
                toast.remove();
            }, 250);
        }, 3500);
    }

    function updateBadge(count) {
        document.querySelectorAll(".cart-badge").forEach(function (badge) {
            badge.textContent = count;
            badge.classList.toggle("d-none", !count);
        });
    }

    function updateBottomBar(count, subtotal) {
        var bar = document.getElementById("cartBottomBar");
        if (!bar) return;
        count = parseInt(count, 10) || 0;
        var onCartPage =
            window.ZOOP_CART_DETAIL_URL &&
            window.location.pathname === window.ZOOP_CART_DETAIL_URL;
        if (count > 0 && !onCartPage) {
            var countEl = document.getElementById("cartBottomBarCount");
            var totalEl = document.getElementById("cartBottomBarTotal");
            if (countEl) countEl.textContent = count + (count === 1 ? " item" : " items");
            if (totalEl && subtotal !== undefined && subtotal !== null) {
                totalEl.textContent = "₹" + subtotal;
            }
            bar.classList.remove("d-none");
            document.body.classList.add("has-cart-bottom-bar");
        } else {
            bar.classList.add("d-none");
            document.body.classList.remove("has-cart-bottom-bar");
        }
    }

    function refreshDrawer() {
        var body = document.getElementById("miniCartBody");
        if (!body || !window.ZOOP_CART_MINI_URL) return;
        fetch(window.ZOOP_CART_MINI_URL, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
        })
            .then(function (response) {
                return response.text();
            })
            .then(function (html) {
                body.innerHTML = html;
            })
            .catch(function () {
                body.innerHTML =
                    '<p class="text-danger small">Could not load your cart. Try again.</p>';
            });
    }

    function refreshCartContent() {
        var container = document.getElementById("cartContent");
        if (!container) return;
        fetch(window.location.pathname, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
        })
            .then(function (response) {
                return response.text();
            })
            .then(function (html) {
                container.innerHTML = html;
            })
            .catch(function () {
                showToast("Could not refresh your cart. Reload the page.");
            });
    }

    function ensureOriginalCaptured(inner) {
        if (inner && !inner.dataset.originalCaptured) {
            inner.dataset.originalHtml = inner.innerHTML;
            inner.dataset.originalCaptured = "1";
        }
    }

    function revertToOriginal(inner) {
        if (inner && inner.dataset.originalHtml !== undefined) {
            inner.innerHTML = inner.dataset.originalHtml;
        }
    }

    function stepperMarkup(cartItemId, quantity) {
        return (
            '<div class="qty-stepper qty-stepper-card" data-qty-stepper data-cart-item-id="' +
            cartItemId +
            '" data-quantity="' +
            quantity +
            '">' +
            '<button type="button" class="qty-btn" data-step="dec" aria-label="Decrease quantity">&minus;</button>' +
            '<span class="qty-value" data-qty-value>' +
            formatQty(quantity) +
            "</span>" +
            '<button type="button" class="qty-btn" data-step="inc" aria-label="Increase quantity">+</button>' +
            "</div>"
        );
    }

    function renderStepperInto(inner, cartItemId, quantity) {
        ensureOriginalCaptured(inner);
        inner.innerHTML = stepperMarkup(cartItemId, quantity);
    }

    function setBusy(el, busy) {
        if (!el) return;
        el.classList.toggle("is-busy", busy);
        el.querySelectorAll("button").forEach(function (btn) {
            btn.disabled = busy;
        });
    }

    function applyMutationResult(originEl, data) {
        updateBadge(data.item_count);
        updateBottomBar(data.item_count, data.preview_subtotal);

        if (originEl.closest("#cartContent")) {
            refreshCartContent();
            return;
        }
        if (originEl.closest("#miniCartBody")) {
            refreshDrawer();
            return;
        }

        var stepper = originEl.matches("[data-qty-stepper]")
            ? originEl
            : originEl.closest("[data-qty-stepper]");
        var inner = stepper ? stepper.closest(".product-add-inner") : null;

        if (!data.item) {
            if (inner) revertToOriginal(inner);
            return;
        }
        if (stepper) {
            stepper.dataset.quantity = data.item.quantity;
            var valueEl = stepper.querySelector("[data-qty-value]");
            if (valueEl) valueEl.textContent = formatQty(data.item.quantity);
        }
    }

    function buildUrl(template, cartItemId) {
        return template.replace("/0/", "/" + cartItemId + "/");
    }

    function updateQuantity(cartItemId, quantity, originEl) {
        setBusy(originEl, true);
        var params = new URLSearchParams();
        params.set("quantity", String(quantity));
        mutateCart(buildUrl(window.ZOOP_CART_UPDATE_URL_TEMPLATE, cartItemId), params)
            .then(function (result) {
                setBusy(originEl, false);
                if (result.data.ok) {
                    applyMutationResult(originEl, result.data);
                } else {
                    showToast(result.data.error || "Could not update quantity.");
                }
            })
            .catch(function () {
                setBusy(originEl, false);
                showToast("Could not update quantity. Check your connection.");
            });
    }

    function removeItem(cartItemId, originEl) {
        setBusy(originEl, true);
        mutateCart(
            buildUrl(window.ZOOP_CART_REMOVE_URL_TEMPLATE, cartItemId),
            new URLSearchParams()
        )
            .then(function (result) {
                setBusy(originEl, false);
                if (result.data.ok) {
                    applyMutationResult(originEl, result.data);
                } else {
                    showToast(result.data.error || "Could not remove item.");
                }
            })
            .catch(function () {
                setBusy(originEl, false);
                showToast("Could not remove item. Check your connection.");
            });
    }

    function handleStep(stepBtn) {
        if (stepBtn.disabled) return;
        var stepper = stepBtn.closest("[data-qty-stepper]");
        if (!stepper) return;
        var cartItemId = stepper.dataset.cartItemId;
        var current = parseFloat(stepper.dataset.quantity || "0");
        var next = stepBtn.dataset.step === "inc" ? current + 1 : current - 1;
        if (next <= 0) {
            removeItem(cartItemId, stepper);
        } else {
            updateQuantity(cartItemId, next, stepper);
        }
    }

    function handleRemove(removeBtn) {
        if (removeBtn.disabled) return;
        var cartItemId = removeBtn.dataset.cartItemId;
        var line = removeBtn.closest("[data-cart-line]") || removeBtn;
        removeItem(cartItemId, line);
    }

    function handleQtyPickerStep(pickerBtn) {
        var picker = pickerBtn.closest("[data-qty-picker]");
        if (!picker) return;
        var input = picker.querySelector("input");
        if (!input) return;
        var current = parseFloat(input.value || "1");
        if (isNaN(current)) current = 1;
        var next = pickerBtn.dataset.pickerStep === "inc" ? current + 1 : current - 1;
        if (next < 1) next = 1;
        input.value = next;
    }

    function handleAddSubmit(event) {
        var form = event.target.closest("form.product-add-form");
        if (!form || !window.ZOOP_CART_ENABLED) return;

        event.preventDefault();
        var inner = form.querySelector(".product-add-inner") || form;
        ensureOriginalCaptured(inner);
        var submitBtn = inner.querySelector("button[type=submit]");
        if (submitBtn) submitBtn.disabled = true;

        mutateCart(form.action, formDataToParams(form))
            .then(function (result) {
                if (result.data.ok) {
                    renderStepperInto(inner, result.data.cart_item_id, result.data.quantity);
                    updateBadge(result.data.item_count);
                    updateBottomBar(result.data.item_count, result.data.preview_subtotal);
                } else if (result.data.login_required) {
                    window.location.href = result.data.redirect;
                } else {
                    if (submitBtn) submitBtn.disabled = false;
                    showToast(result.data.error || "Could not add this item.");
                }
            })
            .catch(function () {
                form.submit();
            });
    }

    function hydrateExistingCartItems() {
        if (!window.ZOOP_CART_ENABLED || !window.ZOOP_CART_SUMMARY_URL) return;
        fetch(window.ZOOP_CART_SUMMARY_URL, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
        })
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                updateBadge(data.item_count);
                updateBottomBar(data.item_count, data.preview_subtotal);
                var byProductCode = {};
                (data.lines || []).forEach(function (line) {
                    byProductCode[line.product_code] = line;
                });
                document
                    .querySelectorAll("form.product-add-form[data-product-code]")
                    .forEach(function (form) {
                        var line = byProductCode[form.dataset.productCode];
                        if (!line) return;
                        var inner = form.querySelector(".product-add-inner") || form;
                        renderStepperInto(inner, line.cart_item_id, line.quantity);
                    });
            })
            .catch(function () {});
    }

    document.addEventListener("submit", handleAddSubmit);

    document.addEventListener("click", function (event) {
        var stepBtn = event.target.closest("[data-step]");
        if (stepBtn) {
            handleStep(stepBtn);
            return;
        }
        var pickerBtn = event.target.closest("[data-picker-step]");
        if (pickerBtn) {
            handleQtyPickerStep(pickerBtn);
            return;
        }
        var removeBtn = event.target.closest("[data-cart-remove]");
        if (removeBtn) {
            handleRemove(removeBtn);
        }
    });

    document.addEventListener("show.bs.offcanvas", function (event) {
        if (event.target && event.target.id === "miniCartOffcanvas") {
            refreshDrawer();
        }
    });

    function init() {
        hydrateExistingCartItems();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
