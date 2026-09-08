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
    // Deliberately the whole page, not just .eo_product_grid: search
    // results (inserted by EasyOrderSearch below) render their own Add to
    // Cart buttons outside the grid, including on the category-tiles page
    // which has no .eo_product_grid at all. Delegating from here means
    // those buttons work without any extra wiring.
    selector: ".eo_page",
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
        const variantId = button.dataset.variantId
            ? parseInt(button.dataset.variantId, 10)
            : undefined;

        const originalLabel = button.textContent;
        button.disabled = true;
        button.textContent = "যোগ হচ্ছে…";

        let result;
        try {
            result = await rpc("/easy-order/cart/add", {
                product_id: productId,
                variant_id: variantId,
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

        button.textContent = "✓ যোগ হয়েছে";
        button.classList.add("eo_added");
        this._updateCartBadge(result.cart_qty);
        // Deliberately stays disabled and labeled "✓ Added" rather than
        // reverting back to "Add to Cart" after a delay — a confirmed,
        // permanent state is clearer than a button that changes back on
        // its own, especially for someone unfamiliar with this kind of
        // interface. To add another unit, they go to the cart page.
    },

    _updateCartBadge(cartQty) {
        const badge = document.querySelector(".eo_cart_count");
        if (badge && typeof cartQty === "number") {
            badge.textContent = cartQty;
            const link = badge.closest(".eo_cart_link");
            if (link) {
                // Restart the CSS animation even if it's already mid-pulse
                // from a previous add (e.g. two quick taps).
                link.classList.remove("eo_pulse");
                void link.offsetWidth; // force reflow so the class re-triggers
                link.classList.add("eo_pulse");
            }
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
            "দুঃখিত, কার্টে যোগ করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        );
    },
});

publicWidget.registry.EasyOrderSearch = publicWidget.Widget.extend({
    selector: ".eo_search_wrap",
    events: {
        "input .eo_search_input": "_onSearchInput",
    },

    /**
     * @override
     */
    start() {
        this._searchTimer = null;
        // Guards against an earlier, slower request resolving after a
        // newer one and overwriting fresher results with stale ones.
        this._searchToken = 0;
        return this._super(...arguments);
    },

    _onSearchInput(ev) {
        const query = ev.currentTarget.value;
        clearTimeout(this._searchTimer);
        // 300ms debounce: fast enough to feel instant, slow enough that
        // a normal typing speed doesn't fire a request per keystroke.
        this._searchTimer = setTimeout(() => this._runSearch(query), 300);
    },

    async _runSearch(query) {
        const resultsEl = this.el.querySelector(".eo_search_results");
        const trimmed = query.trim();

        if (!trimmed) {
            resultsEl.replaceChildren();
            resultsEl.classList.remove("eo_search_results_open");
            return;
        }

        const topCode = this.el.dataset.eoTopCode;
        if (!topCode) {
            // No section in scope (shouldn't happen — the search box
            // only ever renders on category pages) — nothing sensible
            // to search against.
            return;
        }

        const token = ++this._searchToken;
        resultsEl.replaceChildren(...this._buildSkeletonCards());
        resultsEl.classList.add("eo_search_results_open");

        let data;
        try {
            data = await rpc(`/easy-order/${topCode}/search`, { query: trimmed });
        } catch (error) {
            return;
        }
        if (token !== this._searchToken) {
            return;
        }

        const results = (data && data.results) || [];
        resultsEl.replaceChildren();

        if (!results.length) {
            const empty = document.createElement("p");
            empty.className = "eo_search_empty";
            empty.textContent = "কোনো মিল পাওয়া যায়নি।";
            resultsEl.appendChild(empty);
            return;
        }

        for (const item of results) {
            resultsEl.appendChild(this._buildResultCard(item));
        }
    },

    _buildSkeletonCards() {
        const cards = [];
        for (let i = 0; i < 3; i++) {
            const card = document.createElement("div");
            card.className = "eo_search_result eo_search_result_skeleton";
            const img = document.createElement("span");
            img.className = "eo_skeleton_block eo_skeleton_image";
            const info = document.createElement("div");
            info.className = "eo_search_result_info";
            const line1 = document.createElement("span");
            line1.className = "eo_skeleton_block eo_skeleton_line";
            const line2 = document.createElement("span");
            line2.className = "eo_skeleton_block eo_skeleton_line eo_skeleton_line_short";
            info.appendChild(line1);
            info.appendChild(line2);
            card.appendChild(img);
            card.appendChild(info);
            cards.push(card);
        }
        return cards;
    },

    _buildResultCard(item) {
        const card = document.createElement("div");
        card.className = "eo_search_result" + (item.out_of_stock ? " eo_search_result_out_of_stock" : "");

        const img = document.createElement("img");
        img.src = item.image_url;
        img.alt = item.name;
        img.loading = "lazy";
        card.appendChild(img);

        const info = document.createElement("div");
        info.className = "eo_search_result_info";

        const name = document.createElement("p");
        name.className = "eo_search_result_name";
        name.textContent = item.name;
        info.appendChild(name);

        const price = document.createElement("p");
        price.className = "eo_search_result_price";
        price.textContent = item.price_formatted;
        info.appendChild(price);

        card.appendChild(info);

        if (item.out_of_stock) {
            const label = document.createElement("span");
            label.className = "eo_out_of_stock_label";
            label.textContent = "স্টকে নেই";
            card.appendChild(label);
        } else {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "eo_add_btn eo_add_btn_small";
            button.textContent = "কার্টে যোগ করুন";
            button.dataset.productId = item.template_id;
            button.dataset.variantId = item.variant_id;
            card.appendChild(button);
        }

        return card;
    },
});

// Long tile grids (categories or subcategories) are capped to an initial
// 2 rows (8 tiles at 4-per-row) so the page doesn't open with an
// overwhelming wall of tiles. "Show more" reveals one more row at a
// time; "Show all" jumps straight to everything. The template only adds
// [data-eo-truncate] when there are actually more than 11 tiles, so a
// short list renders normally with no buttons at all.
publicWidget.registry.EasyOrderTileTruncate = publicWidget.Widget.extend({
    selector: ".eo_tiles[data-eo-truncate]",

    start() {
        this._setupTruncation();
        return this._super(...arguments);
    },

    _setupTruncation() {
        const INITIAL_COUNT = 8; // 2 rows of 4
        const STEP = 4; // 1 row per "Show more" click

        const tiles = Array.from(this.el.querySelectorAll(":scope > .eo_tile"));
        if (tiles.length <= INITIAL_COUNT) {
            return;
        }

        let visibleCount = INITIAL_COUNT;
        tiles.forEach((tile, index) => {
            tile.classList.toggle("eo_tile_hidden", index >= visibleCount);
        });

        const wrap = document.createElement("div");
        wrap.className = "eo_tiles_more_wrap";

        const moreBtn = document.createElement("button");
        moreBtn.type = "button";
        moreBtn.className = "eo_show_more_btn";
        moreBtn.textContent = "আরও দেখুন";

        const allBtn = document.createElement("button");
        allBtn.type = "button";
        allBtn.className = "eo_show_all_btn";
        allBtn.textContent = `সব দেখুন (${tiles.length})`;

        const reveal = (count) => {
            visibleCount = count;
            tiles.forEach((tile, index) => {
                tile.classList.toggle("eo_tile_hidden", index >= visibleCount);
            });
            if (visibleCount >= tiles.length) {
                wrap.remove();
            }
        };

        moreBtn.addEventListener("click", () => reveal(Math.min(visibleCount + STEP, tiles.length)));
        allBtn.addEventListener("click", () => reveal(tiles.length));

        wrap.appendChild(moreBtn);
        wrap.appendChild(allBtn);
        this.el.insertAdjacentElement("afterend", wrap);
    },
});

// Text-size toggle (A / A+ / A++). The chosen scale is written to a CSS
// custom property on <html> — every font-size in easy_order_interface.scss
// is defined in em relative to .eo_page's own font-size, which reads that
// same property, so one variable scales the whole page. Saved to
// localStorage (not a cookie or the server) since this is a pure display
// preference with nothing for the backend to know about, and it should
// carry over between /easy-order and /easy-order/shop/* on the same
// device without adding a request round-trip just to remember it.
const FONT_SCALE_STORAGE_KEY = "easy_order_font_scale";

publicWidget.registry.EasyOrderFontToggle = publicWidget.Widget.extend({
    selector: ".eo_page",
    events: {
        "click .eo_font_toggle_btn": "_onFontToggleClick",
    },

    start() {
        const saved = window.localStorage.getItem(FONT_SCALE_STORAGE_KEY);
        if (saved) {
            this._applyScale(saved);
        }
        return this._super(...arguments);
    },

    _onFontToggleClick(ev) {
        const scale = ev.currentTarget.dataset.eoFontScale;
        this._applyScale(scale);
        try {
            window.localStorage.setItem(FONT_SCALE_STORAGE_KEY, scale);
        } catch (error) {
            // Private browsing / storage disabled — the toggle still works
            // for the rest of this page view, it just won't carry over to
            // the next page. Not worth bothering the person about.
        }
    },

    _applyScale(scale) {
        document.documentElement.style.setProperty("--eo-font-scale", scale);
        this.el.querySelectorAll(".eo_font_toggle_btn").forEach((btn) => {
            btn.classList.toggle("eo_font_toggle_btn_active", btn.dataset.eoFontScale === scale);
        });
    },
});

// "Recently viewed" categories. This page has no login/account system for
// this kind of shopper, so there's no server-side history to draw on —
// localStorage on this device is the only place this can live. Recorded
// on the category (page_products) screen, displayed on the home
// (page_categories) screen.
const RECENT_CATEGORIES_STORAGE_KEY = "easy_order_recent_categories";
const RECENT_CATEGORIES_MAX = 6;

publicWidget.registry.EasyOrderRecordRecentCategory = publicWidget.Widget.extend({
    selector: ".eo_page[data-category-id]",

    start() {
        const id = this.el.dataset.categoryId;
        const name = this.el.dataset.categoryName;
        const url = this.el.dataset.categoryUrl;
        if (id && name && url) {
            this._recordVisit(id, name, url);
        }
        return this._super(...arguments);
    },

    _recordVisit(id, name, url) {
        let entries = [];
        try {
            entries = JSON.parse(window.localStorage.getItem(RECENT_CATEGORIES_STORAGE_KEY)) || [];
        } catch (error) {
            entries = [];
        }
        entries = entries.filter((entry) => entry.id !== id);
        entries.unshift({ id, name, url });
        entries = entries.slice(0, RECENT_CATEGORIES_MAX);
        try {
            window.localStorage.setItem(RECENT_CATEGORIES_STORAGE_KEY, JSON.stringify(entries));
        } catch (error) {
            // Storage unavailable — recently-viewed just won't be there
            // next visit. Nothing to show the person about that.
        }
    },
});

publicWidget.registry.EasyOrderShowRecentCategories = publicWidget.Widget.extend({
    selector: "#eo_recent_categories",

    start() {
        let entries = [];
        try {
            entries = JSON.parse(window.localStorage.getItem(RECENT_CATEGORIES_STORAGE_KEY)) || [];
        } catch (error) {
            entries = [];
        }
        // Entries saved before this version added a ready-made url
        // wouldn't have one — skip those rather than render a dead
        // link. They'll naturally fall off the list as new visits push
        // them out.
        entries = entries.filter((entry) => entry.url);
        if (entries.length) {
            this._render(entries);
        }
        return this._super(...arguments);
    },

    _render(entries) {
        const itemsEl = this.el.querySelector(".eo_recent_row_items");
        itemsEl.replaceChildren();
        for (const entry of entries) {
            const chip = document.createElement("a");
            chip.className = "eo_recent_chip";
            chip.href = entry.url;
            chip.textContent = entry.name;
            itemsEl.appendChild(chip);
        }
        this.el.style.display = "";
    },
});

// "Can't find it? Tell us" request form: lets the person add more than
// one item row. Pure DOM cloning — no framework needed for something
// this simple, and it degrades gracefully (the form still works with
// just its one row) if this script fails to load for any reason, since
// the form is a plain HTML <form method="post"> underneath.
publicWidget.registry.EasyOrderRequestForm = publicWidget.Widget.extend({
    selector: ".eo_request_form",
    events: {
        "click #eo_add_item_row": "_onAddItemRow",
    },

    _onAddItemRow() {
        const items = this.el.querySelector("#eo_request_items");
        const rows = items.querySelectorAll(".eo_request_item_row");
        const lastRow = rows[rows.length - 1];
        const newRow = lastRow.cloneNode(true);
        newRow.querySelector(".eo_request_item_name").value = "";
        newRow.querySelector(".eo_request_item_qty").value = "1";
        items.appendChild(newRow);
        newRow.querySelector(".eo_request_item_name").focus();
    },
});

export default {
    EasyOrderAddToCart: publicWidget.registry.EasyOrderAddToCart,
    EasyOrderSearch: publicWidget.registry.EasyOrderSearch,
    EasyOrderTileTruncate: publicWidget.registry.EasyOrderTileTruncate,
    EasyOrderFontToggle: publicWidget.registry.EasyOrderFontToggle,
    EasyOrderRecordRecentCategory: publicWidget.registry.EasyOrderRecordRecentCategory,
    EasyOrderShowRecentCategories: publicWidget.registry.EasyOrderShowRecentCategories,
    EasyOrderRequestForm: publicWidget.registry.EasyOrderRequestForm,
};
