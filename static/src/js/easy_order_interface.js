/** @odoo-module **/

/*
 * This module is intentionally self-contained on the website frontend.
 * Do not import @web/legacy/js/public/public_widget or
 * @web/core/network/rpc here: some Odoo 18 frontend asset combinations
 * (especially theme/custom bundles) do not expose those modules in the
 * bundle that renders website.layout. Importing them then prevents the
 * entire Easy Order JS file from loading.
 *
 * The small compatibility layer below provides only the two pieces this
 * page actually needs: widget registration/event delegation and JSON-RPC.
 * It uses the same JSON-RPC wire format as Odoo's frontend RPC helper.
 */
const rpc = async (url, params = {}) => {
    const csrfToken = document.querySelector(".eo_page[data-eo-csrf-token]")?.dataset.eoCsrfToken;
    const rpcParams = csrfToken ? { ...params, csrf_token: csrfToken } : params;
    const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
            jsonrpc: "2.0",
            method: "call",
            params: rpcParams,
        }),
    });

    let payload;
    try {
        payload = await response.json();
    } catch (error) {
        throw new Error(`Invalid RPC response (${response.status})`);
    }

    if (!response.ok || payload?.error) {
        const message = payload?.error?.data?.message ||
            payload?.error?.message ||
            `RPC request failed (${response.status})`;
        throw new Error(message);
    }
    return payload?.result;
};

const publicWidget = (() => {
    const registry = {};

    function makeWidgetClass(definition) {
        class Widget {
            constructor(el) {
                this.el = el;
            }
        }

        Object.assign(Widget.prototype, definition);
        return Widget;
    }

    function bindEvents(instance, definition) {
        const events = definition.events || {};
        for (const [eventSpec, methodName] of Object.entries(events)) {
            const firstSpace = eventSpec.indexOf(" ");
            const eventName = firstSpace > 0 ? eventSpec.slice(0, firstSpace) : eventSpec;
            const selector = firstSpace > 0 ? eventSpec.slice(firstSpace + 1).trim() : null;
            const method = instance[methodName];
            if (!method) continue;

            instance.el.addEventListener(eventName, (nativeEvent) => {
                let target = nativeEvent.target;
                if (selector) {
                    target = target?.closest?.(selector);
                    if (!target || !instance.el.contains(target)) return;
                }

                // publicWidget handlers expect ev.currentTarget to be the
                // element matched by the delegated selector. Native
                // currentTarget is the root listener element, so expose a
                // tiny Proxy rather than mutating the browser Event object.
                const event = selector
                    ? new Proxy(nativeEvent, {
                        get(obj, prop) {
                            if (prop === "currentTarget") return target;
                            const value = obj[prop];
                            // Native Event methods are brand-checked by the
                            // browser. Returning them unbound from a Proxy
                            // makes calls such as ev.preventDefault() throw
                            // "Illegal invocation" in Chromium. Bind all
                            // native methods back to the real Event object.
                            return typeof value === "function" ? value.bind(obj) : value;
                        },
                    })
                    : nativeEvent;
                method.call(instance, event);
            });
        }
    }

    const widgetApi = {
        Widget: {
            extend(definition) {
                const WidgetClass = makeWidgetClass(definition);
                WidgetClass.__definition = definition;
                return WidgetClass;
            },
        },
        registry: {},
        _start() {
            for (const [name, WidgetClass] of Object.entries(widgetApi.registry)) {
                const selector = WidgetClass.__definition?.selector;
                if (!selector) continue;
                document.querySelectorAll(selector).forEach((el) => {
                    const instance = new WidgetClass(el);
                    bindEvents(instance, WidgetClass.__definition);
                    if (typeof instance.start === "function") {
                        Promise.resolve(instance.start()).catch((error) => {
                            console.error(`Easy Order widget ${name} failed to start`, error);
                        });
                    }
                });
            }
        },
    };
    return widgetApi;
})();

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
        return Promise.resolve();
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
        const token = ++this._searchToken;
        resultsEl.replaceChildren(...this._buildSkeletonCards());
        resultsEl.classList.add("eo_search_results_open");

        let data;
        try {
            const searchUrl = topCode
                ? `/easy-order/${topCode}/search`
                : "/easy-order/search";
            data = await rpc(searchUrl, { query: trimmed });
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

        const name = document.createElement("a");
        name.className = "eo_search_result_name eo_product_link";
        name.dataset.variantId = item.variant_id;
        name.href = item.product_url || `/shop/product/${item.template_id}`;
        name.textContent = item.name;
        info.appendChild(name);

        const price = document.createElement("p");
        price.className = "eo_search_result_price";
        price.textContent = item.price_formatted;
        info.appendChild(price);

        card.appendChild(info);

        const favorite = document.createElement("button");
        favorite.type = "button";
        favorite.className = "eo_favorite_btn";
        favorite.dataset.variantId = item.variant_id;
        favorite.textContent = "♡";
        favorite.setAttribute("aria-label", "প্রিয়তে রাখুন");
        card.appendChild(favorite);

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
        return Promise.resolve();
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
        return Promise.resolve();
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
        return Promise.resolve();
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
        return Promise.resolve();
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
// one item row, and adjust quantity with tap-friendly +/- buttons
// instead of typing a number. Pure DOM cloning/manipulation — no
// framework needed for something this simple, and it degrades
// gracefully (the form still works, including the number input itself,
// which accepts typed/scrolled values same as always) if this script
// fails to load for any reason, since the form is a plain HTML
// <form method="post"> underneath.
publicWidget.registry.EasyOrderRequestForm = publicWidget.Widget.extend({
    selector: ".eo_request_form",
    events: {
        "click #eo_add_item_row": "_onAddItemRow",
        "click .eo_qty_btn_minus": "_onQtyMinusClick",
        "click .eo_qty_btn_plus": "_onQtyPlusClick",
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

    _onQtyMinusClick(ev) {
        this._stepQty(ev.currentTarget, -1);
    },

    _onQtyPlusClick(ev) {
        this._stepQty(ev.currentTarget, 1);
    },

    _stepQty(button, delta) {
        const input = button.parentElement.querySelector(".eo_qty_input");
        const min = parseInt(input.min, 10) || 1;
        const current = parseInt(input.value, 10) || min;
        input.value = Math.max(min, current + delta);
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

// Voice search: browser-native Web Speech API with a selectable language,
// interim feedback, multiple alternatives, and a retry-friendly UX.
const EO_VOICE_LANG_KEY = "easy_order_interface.voice_language.v1";

function eoVoiceLanguage() {
    try {
        const value = window.localStorage.getItem(EO_VOICE_LANG_KEY);
        if (["bn-BD", "en-US"].includes(value)) return value;
    } catch (error) {
        // Ignore storage failures.
    }
    return "bn-BD";
}

function eoSetVoiceLanguage(value) {
    if (!["bn-BD", "en-US"].includes(value)) return;
    try { window.localStorage.setItem(EO_VOICE_LANG_KEY, value); } catch (error) {}
}

function eoPickSpeechResult(results) {
    const candidates = [];
    for (let i = 0; i < results.length; i++) {
        const result = results[i];
        for (let j = 0; j < result.length; j++) {
            const alt = result[j];
            if (alt?.transcript?.trim()) {
                candidates.push({
                    text: alt.transcript.trim(),
                    confidence: Number(alt.confidence) || 0,
                });
            }
        }
    }
    candidates.sort((a, b) => b.confidence - a.confidence);
    return candidates[0]?.text || "";
}

function eoConfigureRecognition(Recognition, language, {continuous = false} = {}) {
    const recognition = new Recognition();
    recognition.lang = language;
    recognition.interimResults = true;
    recognition.continuous = continuous;
    recognition.maxAlternatives = 10;
    // Some Chromium versions expose this experimental property. It is safe
    // to set only when supported. Cloud recognition generally gives the best
    // Bengali/English coverage, so keep local-only processing disabled.
    if ("processLocally" in recognition) recognition.processLocally = false;
    return recognition;
}

// Ask for the microphone explicitly before starting speech recognition and
// enable the browser's built-in voice cleanup.  Web Speech normally owns its
// own audio pipeline, but on browsers that support SpeechRecognition.start()
// with an AudioTrack we can feed it a lightly cleaned, mono signal.
async function eoPrepareEnhancedMic() {
    if (!navigator.mediaDevices?.getUserMedia) return {stream: null, track: null};

    const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
            channelCount: {ideal: 1},
            sampleRate: {ideal: 48000},
            sampleSize: {ideal: 16},
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
        },
        video: false,
    });

    const sourceTrack = stream.getAudioTracks()[0] || null;
    if (!sourceTrack) return {stream, track: null};

    // Keep the processing conservative: remove very low rumble and very high
    // hiss, then gently compress the voice so quiet speech is easier to hear.
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return {stream, track: sourceTrack};

    const context = new AudioContextClass();
    if (typeof context.createMediaStreamDestination !== "function") {
        try { context.close(); } catch (error) {}
        return {stream, track: sourceTrack};
    }
    try { await context.resume(); } catch (error) {}
    const source = context.createMediaStreamSource(stream);
    const highpass = context.createBiquadFilter();
    highpass.type = "highpass";
    highpass.frequency.value = 90;
    highpass.Q.value = 0.7;

    const lowpass = context.createBiquadFilter();
    lowpass.type = "lowpass";
    lowpass.frequency.value = 8500;
    lowpass.Q.value = 0.7;

    const compressor = context.createDynamicsCompressor();
    compressor.threshold.value = -24;
    compressor.knee.value = 18;
    compressor.ratio.value = 3;
    compressor.attack.value = 0.008;
    compressor.release.value = 0.22;

    const gain = context.createGain();
    gain.gain.value = 1.10;

    const destination = context.createMediaStreamDestination();
    source.connect(highpass).connect(lowpass).connect(compressor).connect(gain).connect(destination);

    return {
        stream,
        track: destination.stream.getAudioTracks()[0] || sourceTrack,
        cleanup() {
            try { context.close(); } catch (error) {}
        },
    };
}

function eoStartRecognition(recognition, audioTrack) {
    if (audioTrack) {
        try {
            // Experimental Chromium API: use the enhanced microphone track.
            recognition.start(audioTrack);
            return;
        } catch (error) {
            // Fall back to the normal browser microphone pipeline.
        }
    }
    recognition.start();
}

function eoStopMicResources(mic) {
    if (!mic) return;
    try { mic.cleanup?.(); } catch (error) {}
    try { mic.stream?.getTracks().forEach((track) => track.stop()); } catch (error) {}
}

publicWidget.registry.EasyOrderVoiceSearch = publicWidget.Widget.extend({
    selector: ".eo_search_wrap",
    events: {
        "click .eo_voice_btn": "_onVoiceClick",
        "change .eo_voice_language": "_onLanguageChange",
    },

    _onLanguageChange(ev) {
        eoSetVoiceLanguage(ev.currentTarget.value);
    },
    async _onTextKeydown(ev) {
        if (ev.key !== "Enter") return;
        ev.preventDefault();
        const input = ev.currentTarget;
        const text = input.value.trim();
        const resultEl = this.el.querySelector(".eo_assistant_result");
        if (!text) {
            input.focus();
            return;
        }
        input.disabled = true;
        resultEl.textContent = "খুঁজছি…";
        try {
            const data = await rpc("/easy-order/voice/parse", {
                text,
                category_code: this.el.dataset.eoTopCode || null,
            });
            this._renderResult(data?.items || [], text);
        } catch (e) {
            resultEl.textContent = "পণ্যের অর্ডার বুঝতে সমস্যা হয়েছে। আবার লিখুন।";
        } finally {
            input.disabled = false;
            input.focus();
        }
    },

    async _onVoiceClick(ev) {
        ev.preventDefault();
        const input = this.el.querySelector(".eo_search_input");
        const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!Recognition) {
            window.alert("এই ব্রাউজারে কণ্ঠ দিয়ে খোঁজা সমর্থিত নয়। Chrome/Edge ব্যবহার করুন অথবা নিচে লিখে খুঁজুন।");
            return;
        }
        if (this._eo_voice_active) return;

        const button = ev.currentTarget;
        const language = eoVoiceLanguage();
        const recognition = eoConfigureRecognition(Recognition, language);
        let finalText = "";
        let lastInterim = "";
        let mic = null;
        this._eo_voice_active = true;
        button.disabled = true;
        button.classList.add("eo_voice_listening");
        button.textContent = "🔴";
        button.setAttribute("aria-label", "শোনা হচ্ছে");
        input.placeholder = language === "bn-BD" ? "শুনছি… একটু ধীরে পরিষ্কার করে বলুন" : "Listening… speak clearly";

        const finish = () => {
            this._eo_voice_active = false;
            eoStopMicResources(mic);
            button.disabled = false;
            button.classList.remove("eo_voice_listening");
            button.textContent = "🎤";
            button.setAttribute("aria-label", "কণ্ঠ দিয়ে খুঁজুন");
            input.placeholder = "খুঁজুন... (বাংলা বা ইংরেজি)";
            const text = finalText.trim() || lastInterim.trim();
            if (text) {
                input.value = text;
                input.dispatchEvent(new Event("input", { bubbles: true }));
            }
        };

        recognition.onstart = () => {
            button.title = language === "bn-BD" ? "মাইক্রোফোন চালু — কথা বলুন" : "Microphone active — speak now";
        };
        recognition.onaudiostart = () => button.classList.add("eo_voice_hearing");
        recognition.onspeechstart = () => button.classList.add("eo_voice_speech");
        recognition.onspeechend = () => button.classList.remove("eo_voice_speech");
        recognition.onresult = (event) => {
            let interim = "";
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const result = event.results[i];
                const text = eoPickSpeechResult(result);
                if (result.isFinal) finalText += (finalText ? " " : "") + text;
                else interim += (interim ? " " : "") + text;
            }
            lastInterim = interim;
            input.value = finalText || lastInterim;
            input.dispatchEvent(new Event("input", { bubbles: true }));
        };
        recognition.onerror = (event) => {
            if (event.error === "not-allowed" || event.error === "service-not-allowed") {
                input.placeholder = "মাইক্রোফোনের অনুমতি দিন";
            } else if (event.error === "audio-capture") {
                input.placeholder = "মাইক্রোফোন পাওয়া যায়নি — অন্য মাইক নির্বাচন করুন";
            } else if (event.error === "network") {
                input.placeholder = "ভয়েস সার্ভিসে সমস্যা — আবার চেষ্টা করুন";
            } else if (event.error !== "aborted" && event.error !== "no-speech") {
                input.placeholder = "আবার 🎤 চাপুন";
            }
        };
        recognition.onend = finish;

        try {
            mic = await eoPrepareEnhancedMic();
            eoStartRecognition(recognition, mic.track);
        } catch (error) {
            eoStopMicResources(mic);
            this._eo_voice_active = false;
            button.disabled = false;
            button.classList.remove("eo_voice_listening");
            button.textContent = "🎤";
            input.placeholder = error?.name === "NotAllowedError"
                ? "মাইক্রোফোনের অনুমতি দিন"
                : "মাইক্রোফোন চালু করা যায়নি — আবার চেষ্টা করুন";
        }
    },
});

const EO_FAVORITES_KEY = "easy_order_interface.favorite_variants.v1";

function eoGetFavorites() {
    try {
        const values = JSON.parse(window.localStorage.getItem(EO_FAVORITES_KEY) || "[]");
        return Array.isArray(values) ? values.map(Number).filter(Boolean) : [];
    } catch (error) {
        return [];
    }
}

function eoSetFavorites(values) {
    try {
        window.localStorage.setItem(EO_FAVORITES_KEY, JSON.stringify([...new Set(values)].slice(0, 100)));
    } catch (error) {
        // Private browsing/storage-disabled browsers simply get no persistence.
    }
}

function eoToggleFavorite(variantId) {
    const id = Number(variantId);
    if (!id) return false;
    const favorites = eoGetFavorites();
    const index = favorites.indexOf(id);
    if (index >= 0) {
        favorites.splice(index, 1);
        eoSetFavorites(favorites);
        return false;
    }
    favorites.unshift(id);
    eoSetFavorites(favorites);
    return true;
}

function eoSyncFavoriteButtons(root = document) {
    const favorites = new Set(eoGetFavorites());
    root.querySelectorAll(".eo_favorite_btn[data-variant-id]").forEach((button) => {
        const active = favorites.has(Number(button.dataset.variantId));
        button.classList.toggle("eo_favorite_active", active);
        button.textContent = active ? "♥" : "♡";
        button.setAttribute("aria-label", active ? "প্রিয় থেকে সরান" : "প্রিয়তে রাখুন");
    });
}

publicWidget.registry.EasyOrderFavorites = publicWidget.Widget.extend({
    selector: ".eo_page",
    events: {
        "click .eo_favorite_btn": "_onFavoriteClick",
    },

    start() {
        eoSyncFavoriteButtons(this.el);
        return Promise.resolve();
    },

    _onFavoriteClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const button = ev.currentTarget;
        const active = eoToggleFavorite(button.dataset.variantId);
        eoSyncFavoriteButtons(this.el);
        if (this.el.dataset.eoFavoritesPage) {
            const card = button.closest(".eo_search_result, .eo_product_card");
            if (!active && card) card.remove();
            const grid = this.el.querySelector(".eo_favorites_grid");
            if (grid && !grid.children.length) {
                this.el.querySelector(".eo_favorites_empty")?.style.removeProperty("display");
            }
        }
    },
});

publicWidget.registry.EasyOrderPagination = publicWidget.Widget.extend({
    selector: ".eo_pagination[data-eo-pagination]",

    events: {
        "click .eo_load_more_btn": "_onLoadMore",
    },

    start() {
        this._loading = false;
        this.categoryId = this.el.closest(".eo_page")?.dataset.categoryId;
        this.topCode = this.el.closest(".eo_page")?.dataset.eoTopCode;
        this.offset = Number(this.el.dataset.eoOffset || 0);
        this.total = Number(this.el.dataset.eoTotal || 0);
        this.limit = Number(this.el.dataset.eoLimit || 24);
        return Promise.resolve();
    },

    async _onLoadMore(ev) {
        if (this._loading || !this.topCode || !this.categoryId) return;
        this._loading = true;
        const button = ev.currentTarget;
        button.disabled = true;
        button.textContent = "লোড হচ্ছে…";
        try {
            const data = await rpc(`/easy-order/${this.topCode}/products`, {
                category_id: this.categoryId,
                offset: this.offset,
                limit: this.limit,
            });
            const products = (data && data.products) || [];
            const grid = this.el.closest(".eo_page")?.querySelector(".eo_product_grid");
            if (grid) products.forEach((item) => grid.appendChild(this._buildProductCard(item)));
            this.offset = data?.next_offset ?? (this.offset + products.length);
            eoSyncFavoriteButtons(grid || this.el);
            if (!data?.next_offset || !products.length || this.offset >= this.total) {
                this.el.remove();
                return;
            }
            button.disabled = false;
            button.textContent = "আরও পণ্য দেখুন";
        } catch (error) {
            button.disabled = false;
            button.textContent = "আবার চেষ্টা করুন";
        } finally {
            this._loading = false;
        }
    },

    _buildProductCard(item) {
        const card = document.createElement("div");
        card.className = "eo_product_card" + (item.out_of_stock ? " eo_product_card_out_of_stock" : "");
        const main = document.createElement("div");
        main.className = "eo_product_card_main";
        const img = document.createElement("img");
        img.className = "eo_product_image";
        img.src = item.image_url;
        img.alt = item.name;
        img.loading = "lazy";
        main.appendChild(img);
        const info = document.createElement("div");
        info.className = "eo_product_info";
        const name = document.createElement("a");
        name.className = "eo_product_name eo_product_link";
        name.dataset.variantId = item.variant_id;
        name.href = item.product_url || `/shop/product/${item.template_id}`;
        name.textContent = item.name;
        const price = document.createElement("p");
        price.className = "eo_product_price";
        price.textContent = item.price_formatted;
        info.append(name, price);
        main.appendChild(info);
        card.appendChild(main);
        const fav = document.createElement("button");
        fav.type = "button";
        fav.className = "eo_favorite_btn";
        fav.dataset.variantId = item.variant_id;
        fav.textContent = "♡";
        fav.setAttribute("aria-label", "প্রিয়তে রাখুন");
        card.appendChild(fav);
        if (item.out_of_stock) {
            const label = document.createElement("span");
            label.className = "eo_out_of_stock_label";
            label.textContent = "স্টকে নেই";
            card.appendChild(label);
        } else {
            const add = document.createElement("button");
            add.type = "button";
            add.className = "eo_add_btn";
            add.textContent = "কার্টে যোগ করুন";
            add.dataset.productId = item.template_id;
            add.dataset.variantId = item.variant_id;
            card.appendChild(add);
        }
        return card;
    },
});

publicWidget.registry.EasyOrderFavoritesPage = publicWidget.Widget.extend({
    selector: ".eo_page[data-eo-favorites-page]",

    async start() {
        const grid = this.el.querySelector(".eo_favorites_grid");
        const empty = this.el.querySelector(".eo_favorites_empty");
        const ids = eoGetFavorites();
        if (!ids.length) {
            empty?.style.removeProperty("display");
            return Promise.resolve();
        }
        try {
            // Favorites are browser-local by design, so this page only asks
            // the server to validate the IDs and return current catalog data.
            const data = await rpc("/easy-order/favorites/data", { product_ids: ids });
            const products = data?.products || [];
            if (!products.length) {
                empty?.style.removeProperty("display");
                return Promise.resolve();
            }
            for (const item of products) {
                const card = document.createElement("div");
                card.className = "eo_search_result";
                const img = document.createElement("img");
                img.src = item.image_url;
                img.alt = item.name;
                img.loading = "lazy";
                card.appendChild(img);
                const info = document.createElement("div");
                info.className = "eo_search_result_info";
                const name = document.createElement("a"); name.className = "eo_search_result_name eo_product_link"; name.dataset.variantId = item.variant_id; name.href = item.product_url || `/shop/product/${item.template_id}`; name.textContent = item.name;
                const price = document.createElement("p"); price.className = "eo_search_result_price"; price.textContent = item.price_formatted;
                info.append(name, price); card.appendChild(info);
                const fav = document.createElement("button");
                fav.type = "button"; fav.className = "eo_favorite_btn"; fav.dataset.variantId = item.variant_id; fav.textContent = "♥";
                fav.setAttribute("aria-label", "প্রিয় থেকে সরান"); card.appendChild(fav);
                if (!item.out_of_stock) {
                    const add = document.createElement("button"); add.type = "button"; add.className = "eo_add_btn eo_add_btn_small"; add.textContent = "কার্টে যোগ করুন";
                    add.dataset.productId = item.template_id; add.dataset.variantId = item.variant_id; card.appendChild(add);
                } else {
                    const label = document.createElement("span"); label.className = "eo_out_of_stock_label"; label.textContent = "স্টকে নেই"; card.appendChild(label);
                }
                grid.appendChild(card);
            }
            eoSyncFavoriteButtons(this.el);
        } catch (error) {
            empty?.style.removeProperty("display");
        }
        return Promise.resolve();
    },
});

// Account-synchronised favorites: guest favorites stay in localStorage;
// logged-in customers additionally merge them into Odoo so the list follows
// them across devices. Failure is intentionally silent so guests never see
// an authentication error.
publicWidget.registry.EasyOrderFavoriteSync = publicWidget.Widget.extend({
    selector: ".eo_page",
    async start() {
        const local = eoGetFavorites();
        try {
            const data = await rpc("/easy-order/favorites/sync", { product_ids: local });
            if (Array.isArray(data?.product_ids)) {
                eoSetFavorites([...new Set([...local, ...data.product_ids])]);
                eoSyncFavoriteButtons(this.el);
            }
        } catch (error) {
            // Public/guest session or unavailable endpoint: local favorites remain.
        }
        return Promise.resolve();
    },
});

// Send favorite removals to the account store when possible.
const _eoOriginalToggleFavorite = eoToggleFavorite;
eoToggleFavorite = function (variantId) {
    const wasActive = eoGetFavorites().includes(Number(variantId));
    const active = _eoOriginalToggleFavorite(variantId);
    if (wasActive) {
        rpc("/easy-order/favorites/remove", { product_id: Number(variantId) }).catch(() => {});
    } else {
        rpc("/easy-order/favorites/sync", { product_ids: [Number(variantId)] }).catch(() => {});
    }
    return active;
};

// Recently viewed products. A product is recorded when its name/link is
// opened, not merely because it appeared in a list.
const EO_RECENT_PRODUCTS_KEY = "easy_order_recent_products.v1";
const EO_RECENT_PRODUCTS_MAX = 8;
function eoRecordRecentProduct(id, name, url, imageUrl) {
    if (!id || !url) return;
    let items = [];
    try { items = JSON.parse(localStorage.getItem(EO_RECENT_PRODUCTS_KEY) || "[]"); } catch (e) {}
    items = Array.isArray(items) ? items.filter(x => Number(x.id) !== Number(id)) : [];
    items.unshift({ id: Number(id), name: name || "", url, image_url: imageUrl || "" });
    try { localStorage.setItem(EO_RECENT_PRODUCTS_KEY, JSON.stringify(items.slice(0, EO_RECENT_PRODUCTS_MAX))); } catch (e) {}
}
function eoGetRecentProducts() {
    try {
        const items = JSON.parse(localStorage.getItem(EO_RECENT_PRODUCTS_KEY) || "[]");
        return Array.isArray(items) ? items.slice(0, EO_RECENT_PRODUCTS_MAX) : [];
    } catch (e) { return []; }
}
publicWidget.registry.EasyOrderRecentProducts = publicWidget.Widget.extend({
    selector: ".eo_page",
    events: { "click .eo_product_link": "_record" },
    _record(ev) {
        const link = ev.currentTarget;
        eoRecordRecentProduct(link.closest(".eo_product_card, .eo_search_result")?.dataset.variantId || link.dataset.productId, link.textContent.trim(), link.href, link.closest(".eo_product_card, .eo_search_result")?.querySelector("img")?.src);
    },
});
publicWidget.registry.EasyOrderShowRecentProducts = publicWidget.Widget.extend({
    selector: "#eo_recent_products",
    start() {
        const items = eoGetRecentProducts();
        if (!items.length) return Promise.resolve();
        const wrap = this.el.querySelector(".eo_recent_row_items");
        for (const item of items) {
            const a = document.createElement("a"); a.className = "eo_recent_product_chip"; a.href = item.url;
            if (item.image_url) { const img = document.createElement("img"); img.src=item.image_url; img.alt=""; a.appendChild(img); }
            const span=document.createElement("span"); span.textContent=item.name; a.appendChild(span); wrap.appendChild(a);
        }
        this.el.style.display = "";
        return Promise.resolve();
    },
});

// Voice assistant ordering: speech -> deterministic Odoo catalog matching ->
// explicit confirmation -> cart. It never submits an order without a tap.
publicWidget.registry.EasyOrderVoiceAssistant = publicWidget.Widget.extend({
    selector: ".eo_voice_assistant",
    events: {
        "click .eo_assistant_btn": "_startVoice",
        "change .eo_voice_language": "_onLanguageChange",
        "keydown .eo_assistant_text_input": "_onTextKeydown",
    },
    _onLanguageChange(ev) {
        eoSetVoiceLanguage(ev.currentTarget.value);
    },
    async _startVoice(ev) {
        const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const resultEl = this.el.querySelector(".eo_assistant_result");
        const languageSelect = this.el.querySelector(".eo_voice_language");
        if (languageSelect) languageSelect.value = eoVoiceLanguage();
        if (!Recognition) {
            resultEl.textContent = "এই ব্রাউজারে কণ্ঠ দিয়ে অর্ডার সমর্থিত নয়। Chrome/Edge ব্যবহার করুন।";
            return;
        }
        if (this._eo_voice_active) return;

        const recognition = eoConfigureRecognition(Recognition, eoVoiceLanguage());
        const button = ev.currentTarget;
        button.disabled = true;
        button.classList.add("eo_voice_listening");
        button.textContent = "🔴 শুনছি…";
        let finalText = "";
        let interimText = "";
        let mic = null;
        this._eo_voice_active = true;

        recognition.onstart = () => {
            resultEl.textContent = "মাইক্রোফোন প্রস্তুত। পরিষ্কার করে কথা বলুন…";
        };
        recognition.onresult = async (event) => {
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const result = event.results[i];
                const text = eoPickSpeechResult(result);
                if (result.isFinal) finalText += (finalText ? " " : "") + text;
                else interimText = text;
            }
            resultEl.textContent = `আপনি বলেছেন: “${finalText || interimText}”`;
            if (!finalText.trim()) return;
            try {
                const data = await rpc("/easy-order/voice/parse", {
                    text: finalText.trim(),
                    category_code: this.el.dataset.eoTopCode || null,
                });
                this._renderResult(data?.items || [], finalText.trim());
            } catch (e) {
                resultEl.textContent = "কণ্ঠের অর্ডার বুঝতে সমস্যা হয়েছে। আবার বলুন।";
            }
        };
        recognition.onerror = (event) => {
            if (event.error === "not-allowed" || event.error === "service-not-allowed") {
                resultEl.textContent = "মাইক্রোফোনের অনুমতি দিন।";
            } else if (event.error === "audio-capture") {
                resultEl.textContent = "মাইক্রোফোন পাওয়া যায়নি — অন্য মাইক নির্বাচন করুন।";
            } else if (event.error === "network") {
                resultEl.textContent = "ভয়েস সার্ভিসে সমস্যা হয়েছে — আবার চেষ্টা করুন।";
            } else if (event.error !== "aborted" && event.error !== "no-speech") {
                resultEl.textContent = "কণ্ঠ শোনা যায়নি। আবার চেষ্টা করুন।";
            }
        };
        recognition.onend = () => {
            this._eo_voice_active = false;
            eoStopMicResources(mic);
            button.disabled = false;
            button.classList.remove("eo_voice_listening", "eo_voice_hearing", "eo_voice_speech");
            button.textContent = "🎤 অর্ডার বলে দিন";
        };

        try {
            mic = await eoPrepareEnhancedMic();
            eoStartRecognition(recognition, mic.track);
        } catch (e) {
            eoStopMicResources(mic);
            this._eo_voice_active = false;
            button.disabled = false;
            button.classList.remove("eo_voice_listening");
            button.textContent = "🎤 অর্ডার বলে দিন";
            resultEl.textContent = e?.name === "NotAllowedError"
                ? "মাইক্রোফোনের অনুমতি দিন।"
                : "মাইক্রোফোন চালু করা যায়নি — আবার চেষ্টা করুন।";
        }
    },
    _renderResult(items,text){
        const resultEl=this.el.querySelector(".eo_assistant_result"); resultEl.replaceChildren();
        const title=document.createElement("p"); title.className="eo_assistant_transcript"; title.textContent=`আপনি বলেছেন: “${text}”`; resultEl.appendChild(title);
        if(!items.length){ resultEl.appendChild(Object.assign(document.createElement("p"),{textContent:"কোনো নিশ্চিত পণ্য মিলেনি। পণ্যের নাম আরেকটু পরিষ্কার করে বলুন।"})); return; }
        const list=document.createElement("div"); list.className="eo_assistant_items";
        for(const item of items){ const row=document.createElement("div"); row.className="eo_assistant_item"; row.innerHTML=`<span>${item.name}</span><strong>× ${item.qty}</strong>`; list.appendChild(row); }
        resultEl.appendChild(list);
        const add=document.createElement("button"); add.type="button"; add.className="eo_add_btn eo_assistant_confirm"; add.textContent="✓ সবগুলো কার্টে যোগ করুন";
        add.addEventListener("click",async()=>{
            add.disabled=true; add.textContent="যোগ হচ্ছে…";
            for(const item of items){ if(!item.out_of_stock) await rpc("/easy-order/cart/add",{product_id:item.template_id,variant_id:item.variant_id,qty:item.qty}); }
            add.textContent="✓ কার্টে যোগ হয়েছে";
        });
        resultEl.appendChild(add);
    },
});

// Basic PWA registration. The service worker is network-first and falls back
// to cache when offline; it never caches POST/JSON cart mutations.
publicWidget.registry.EasyOrderPWA = publicWidget.Widget.extend({
    selector: ".eo_page",
    start() {
        if ("serviceWorker" in navigator) navigator.serviceWorker.register("/easy-order/service-worker.js", {scope:"/easy-order/"}).catch(()=>{});
        return Promise.resolve();
    },
});

// Start only after every widget registration above has been defined.
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => publicWidget._start(), { once: true });
} else {
    publicWidget._start();
}
