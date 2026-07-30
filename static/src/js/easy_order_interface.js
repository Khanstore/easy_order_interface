/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

// Frontend (website) interactivity in Odoo 18 still goes through
// publicWidget rather than mounting a full OWL component — OWL v3 is
// used for the pieces of this module that need it, but a page this
// simple (one delegated click handler) doesn't need component state,
// so publicWidget keeps it small. `rpc` (not the older ajax.jsonRpc)
// is the current, non-deprecated way to call a type="json" route.
publicWidget.registry.EasyOrderAddToCart = publicWidget.Widget.extend({
    selector: ".eo_product_grid",
    events: {
        "click .eo_add_btn": "_onAddToCartClick",
    },

    async _onAddToCartClick(ev) {
        const button = ev.currentTarget;
        if (button.disabled) {
            return;
        }

        const productId = parseInt(button.dataset.productId, 10);
        if (!productId) {
            return;
        }

        const originalLabel = button.textContent;
        button.disabled = true;
        button.textContent = "Adding…";

        let result;
        try {
            result = await rpc("/easy-order/cart/add", {
                product_id: productId,
                qty: 1,
            });
        } catch (error) {
            this._showError(button, originalLabel);
            return;
        }

        if (result && result.error) {
            this._showError(button, originalLabel, result.error);
            return;
        }

        button.textContent = "✓ Added";
        button.classList.add("eo_added");
        this._updateCartBadge(result.cart_qty);

        // Let the person add it again (e.g. a second unit) after a
        // moment, instead of leaving the button permanently disabled.
        setTimeout(() => {
            button.disabled = false;
            button.textContent = originalLabel;
            button.classList.remove("eo_added");
        }, 1500);
    },

    _updateCartBadge(cartQty) {
        const badge = document.querySelector(".eo_cart_count");
        if (badge && typeof cartQty === "number") {
            badge.textContent = cartQty;
        }
    },

    _showError(button, originalLabel, message) {
        button.disabled = false;
        button.textContent = originalLabel;
        // A plain alert() is intentional here: it's the most
        // screen-reader- and low-vision-friendly way to surface a
        // failure on a page built for first-time online shoppers,
        // versus a toast that might disappear before it's read.
        window.alert(
            message ||
            "Sorry, something went wrong adding that to your cart. Please try again."
        );
    },
});

export default publicWidget.registry.EasyOrderAddToCart;
