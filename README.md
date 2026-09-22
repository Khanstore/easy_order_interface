## 18.0.4.4.2

- Fixed Odoo 18 frontend crash: removed legacy `this._super(...arguments)` calls from `publicWidget` lifecycle methods. Odoo 18 does not provide `_super` on these registry widget instances.

# Easy Order Interface

**Odoo 18 module — version 18.0.4.4.2**

A simplified, high-accessibility storefront designed to make ordering easier for older and low-vision customers.

## Documentation

- **User Manual:** `docs/USER_MANUAL.md`
- **Developer Manual:** `docs/DEVELOPER_MANUAL.md`

The manuals are maintained as part of the module and should be updated whenever the user workflow, configuration, architecture, security, or performance behavior changes.

## Core design

- Uses a separate Easy Order category tree so the simplified interface can be organized independently of the normal eCommerce navigation.
- Uses Odoo's native `website.sale_get_order()` and `sale.order._cart_update()` for the real shopping cart.
- Keeps checkout on Odoo's standard flow instead of duplicating payment/address/delivery logic.
- Provides forgiving English/Bengali/Romanized-Bengali search.
- Provides a free-text customer request workflow for products that cannot be found.
- Lets staff use product suggestions before converting a request into a normal sale order.
- Bundles Atkinson Hyperlegible locally for legibility.

## Current performance protections

- Frontend search is debounced by 300 ms.
- Stale search responses are ignored.
- Search uses SQL prefiltering before Python fuzzy scoring.
- Product images use lazy loading.
- The UI avoids loading a separate frontend framework just for simple delegated interactions.

## Recommended next improvements

For a larger production catalog, prioritize:

1. Product pagination/infinite loading.
2. Short-lived caching for Popular products.
3. Profiling and batching expensive price calculations.
4. Hierarchical category optimization if the category tree becomes very large.
5. Search analytics for zero-result queries.

For older users, prioritize:

1. Voice search.
2. Buy Again / Recent Orders.
3. Favorites.
4. Large quantity controls.
5. A simple order-review step.

See the Developer Manual for implementation guidance and the User Manual for operating instructions.


## Version 18.0.4.4.2 — accessibility and performance features

This release adds four customer-facing improvements:
- **Voice Search:** microphone search using the browser Web Speech API, with a graceful text-search fallback.
- **Buy Again:** logged-in customers see products from their recent confirmed/completed orders on the Easy Order home page. No order history is exposed to public visitors.
- **Favorites:** browser-local favorite products with a dedicated Favorites page. The server validates favorite product IDs before displaying current catalog data.
- **Pagination / Load More:** category product lists load an initial page of 24 products and fetch more on demand, reducing initial database work, price calculations, HTML size, and browser rendering.

The user manual and developer manual should be updated whenever these workflows or their implementation change.


## Version 18.0.4.4.2 — reliability and correctness pass

This maintenance release corrects several issues found during a source-level review:
- Popular products are now calculated from the full category scope instead of only the first paginated page.
- Search category matching is restricted to the current Easy Order section.
- Add to Cart rejects inactive/non-saleable templates before mutating the cart.
- Unexpected cart exceptions are logged server-side instead of being silently swallowed.
- Category parent recursion is blocked.
- Request quantities must be positive and matched products must be active/saleable before order creation.
- Buy Again price display uses the same computed website price data as the category product display.


## Version 18.0.4.4.2 — assistant, recommendations and mobile

Adds Smart Recommendations, Recently Viewed Products, One-Tap Reorder, Simple Checkout, Order Tracking, Voice Assistant Ordering, price-aware Smart Search, account-synchronised Favorites, and basic PWA installability.


### Voice recognition improvement (18.0.4.4.3)
- Voice language can be selected between Bangla (`bn-BD`) and English (`en-US`).
- Recognition now uses interim results and up to five alternatives, then selects the highest-confidence transcript.
- Voice assistant keeps listening feedback and sends only the final transcript to the Odoo catalog matcher.
- The selected language is remembered locally in the browser.
