## 18.0.4.4.2

- Fixed Odoo 18 frontend crash: removed legacy `this._super(...arguments)` calls from `publicWidget` lifecycle methods. Odoo 18 does not provide `_super` on these registry widget instances.

# Easy Order Interface — Developer Manual

**Module:** Easy Order Interface  
**Version:** 18.0.4.3.1  
**Platform:** Odoo 18  
**License:** LGPL-3

## 1. Purpose and architecture

This module provides a separate, accessibility-focused storefront at `/easy-order` while reusing Odoo's native eCommerce cart and checkout machinery.

The key design principle is:

> Easy Order owns the simplified browsing/request experience, but Odoo owns the real cart and sale order lifecycle.

This prevents the module from maintaining a second order/cart implementation.

## 2. File structure

```text
easy_order_interface/
├── __init__.py
├── __manifest__.py
├── README.md
├── search_matching.py
├── controllers/
│   ├── __init__.py
│   └── main.py
├── models/
│   ├── __init__.py
│   ├── easy_order_category.py
│   ├── easy_order_category_import_wizard.py
│   ├── easy_order_request.py
│   ├── easy_order_request_suggest_wizard.py
│   └── product_template.py
├── security/
│   └── ir.model.access.csv
├── views/
│   ├── templates.xml
│   ├── easy_order_request_views.xml
│   ├── easy_order_category_views.xml
│   └── easy_order_category_import_wizard_views.xml
├── static/src/
│   ├── fonts/
│   ├── js/easy_order_interface.js
│   └── scss/
└── docs/
    ├── USER_MANUAL.md
    └── DEVELOPER_MANUAL.md
```

## 3. Models

### `easy.order.category`

A separate hierarchical category structure for the Easy Order storefront.

Important fields:

- `name`: internal name.
- `public_name`: customer-facing name.
- `code`: top-level URL identifier.
- `image`: category image.
- `sequence`: sibling ordering.
- `parent_id` / `child_ids`: hierarchy.
- `category_path`: stored readable path.
- `include_subcategory_products`: controls inherited product display.
- `product_tmpl_ids`: products assigned to the category.

The model deliberately does not reuse `product.public.category` because Easy Order navigation may need to be reorganized independently of the normal storefront.

### `easy.order.request`

Stores a customer-described request before it has been matched to real products.

States:

- `new`
- `processed`

The record links to `sale.order` after conversion.

### `easy.order.request.line`

Stores:

- `probable_name`: what the customer said.
- `product_id`: matched real Odoo product variant.
- `qty`: requested quantity.

### `easy.order.request.line.suggest.wizard`

A transient helper that runs the same search-matching engine against the whole saleable catalog and returns a small set of suggested product templates.

## 4. Controllers and routes

### `/easy-order`

Top-level category directory.

### `/easy-order/<code>`

Top-level category page.

### `/easy-order/<code>/shop/<category>`

Nested category page.

### `/easy-order/<code>/search`

JSON search endpoint scoped to the top-level category.

### `/easy-order/cart/add`

JSON cart-add endpoint. It delegates cart mutation to Odoo's website sale order machinery.

### Request form routes

The request form and submit/thank-you routes are implemented in `controllers/main.py`. Keep request creation separate from `sale.order` creation: an unreviewed customer description is not a real order.

## 5. Cart integration

The cart implementation intentionally uses:

- `request.website.sale_get_order()`
- `sale.order._cart_update(...)`

Do not introduce a second cart model or duplicate sale order records merely to support Easy Order.

When extending Add to Cart, preserve Odoo's normal behavior for:

- Pricelists.
- Taxes.
- Currency.
- Stock rules.
- Existing session cart.
- Standard checkout.

## 6. Search architecture

`search_matching.py` contains pure-Python matching helpers so both frontend search and backend request suggestions can use the same logic.

The pipeline is:

1. Normalize input.
2. Expand glossary terms.
3. Build a broad SQL `ilike` candidate domain.
4. Limit the candidate set.
5. Tokenize product names/category names.
6. Score exact, prefix, substring, and limited edit-distance matches.
7. Require every query word to find a match.
8. Return the highest-scoring results.

The glossary currently contains a starter English/Bengali vocabulary. It is intentionally code-based rather than a database model.

## 7. Search performance considerations

The public search runs after a 300 ms frontend debounce. The JavaScript also uses a request token so a slower old request cannot overwrite a newer result.

The backend uses SQL prefiltering before Python fuzzy scoring. This is important: do not replace the candidate prefilter with a Python loop over the entire catalog for every keystroke.

### Recommended next optimization for large catalogs

If the catalog becomes large, introduce a dedicated indexed search strategy rather than continually increasing the Python candidate limit.

Potential approaches, in increasing complexity:

1. Store/search a normalized product search key.
2. Add database indexes appropriate to the actual Odoo/PostgreSQL workload.
3. Cache stable glossary/normalization data.
4. Use a dedicated search service only if catalog size and traffic justify it.

Do not add an external search engine prematurely.

## 8. Page-rendering performance

Current category rendering performs several operations that can become expensive for large categories:

- Loading all variants for the category.
- Computing display prices per variant.
- Computing stock status per variant.
- Running a sales-history aggregation for Popular products.
- Rendering all products in one page.

### Recommended production improvements

**Priority 1 — pagination/infinite loading**

Do not render hundreds or thousands of products on one page. Return a small first page and load more on demand.

**Priority 1 — lazy Popular data**

Popular products can be loaded only when enough sales history exists or cached for a short period. Avoid recalculating popularity on every category request for high-traffic sites.

**Priority 1 — batch expensive product calculations**

Profile `_get_invoiced_price()` on the actual Odoo database. If it becomes a bottleneck, replace per-product computation with an appropriate batched price computation that still respects the active website, pricelist, currency, taxes, and product variants.

**Priority 2 — hierarchical queries**

If the category model grows substantially, consider using Odoo's hierarchical/parent-store facilities rather than recursively walking every descendant in Python.

**Priority 2 — cache stable category metadata**

Top-level category data, category images, and other relatively stable metadata can be cached where invalidation is safe.

Always profile before introducing caching. Incorrect cache invalidation is worse than a small performance cost.

## 9. Accessibility and UX extension rules

This module is designed for older and low-vision users. New UI should follow these rules:

- Keep primary actions large and easy to tap.
- Avoid tiny icon-only controls.
- Preserve visible text labels.
- Keep focus states visible.
- Do not rely on color alone to communicate state.
- Avoid disappearing notifications for important actions.
- Use plain language.
- Keep navigation predictable.
- Prefer one major decision per screen.
- Keep touch targets comfortably large.

Atkinson Hyperlegible is bundled locally to avoid an external font dependency.

## 10. Recommended future features

### High value for older users

1. **Large quantity control** — make adding 2, 3, or more units simple without sending the customer into a complex cart screen.
2. **Simple order confirmation screen** — show item, quantity, total, and a very clear next action before checkout.
3. **Persistent Call to Order** — keep the configured phone/WhatsApp action visible without competing with Add to Cart.
4. **Optional text-to-speech** — read product/category information aloud when requested by the customer.
5. **Recently viewed products** — extend the existing recently viewed category feature to products.
6. **Configurable voice-search language** — allow Bengali/English or browser-language selection instead of a fixed language.
7. **Account-synchronized Favorites** — optionally sync favorites across devices while retaining browser-local mode for guests.

### Operational features

8. **Request assignment** — assign Easy Order Requests to a sales user.
9. **Request priority** — normal/high/urgent.
10. **Request notes and internal communication** — useful for phone-assisted ordering.
11. **Request history** — show previous requests/orders for a returning phone number.
12. **Search analytics** — record searches with zero results so staff know what customers are trying to find.

### Technical features

13. **Short-lived popularity cache** for high-traffic stores.
14. **Batch price/stock computation after profiling**.
15. **Automated tests** for routes, search ranking, category isolation, cart addition, request conversion, and security.
16. **Performance regression tests** for catalogs of realistic sizes.

## 11. Security rules

Public routes must only expose products that are intentionally public/saleable through the Easy Order interface.

Do not expose arbitrary backend model records from JSON routes.

For new JSON endpoints:

- Validate IDs received from the browser.
- Re-check website/publication/saleability rules server-side.
- Do not trust frontend stock status.
- Preserve CSRF protection where applicable.
- Do not allow a public user to write arbitrary Odoo model fields.
- Use `sudo()` only where required, and narrow the data returned afterward.

## 12. Development workflow

Before changing behavior:

1. Read this manual and the User Manual.
2. Identify whether the change belongs in model, controller, template, JS, or SCSS.
3. Preserve the separation between Easy Order and the normal storefront.
4. Preserve native Odoo cart/checkout behavior.
5. Test public access and logged-in staff access separately.
6. Test mobile and desktop.
7. Test Bengali and English input.
8. Test empty, slow, and large result sets.
9. Update both manuals when the user-visible workflow or developer architecture changes.
10. Record the change in the module version/changelog when appropriate.

## 13. Debugging checklist

### Frontend JS

Check browser console for:

- Missing Odoo modules.
- RPC errors.
- JavaScript exceptions.
- Incorrect data attributes.

The JS is intentionally loaded in `web.assets_frontend` because its imports depend on Odoo's frontend module graph.

### Search

Check:

- SQL candidate domain.
- Glossary expansion.
- Normalization.
- Candidate limit.
- Python score.
- Top-level category scope.

### Cart

Check:

- Product/variant IDs.
- Current website order.
- `_cart_update()` result.
- Pricelist/currency context.
- Stock rules.

### Requests

Check:

- All request lines have a real product before conversion.
- Partner matching by phone/mobile.
- Sale order creation.
- Request state transition.
- Link to created sale order.

## 14. Documentation maintenance

These manuals are part of the module, not external notes.

Whenever a feature changes:

- Update **USER_MANUAL.md** if the customer/staff workflow changes.
- Update **DEVELOPER_MANUAL.md** if code architecture, routes, models, extension points, security, or performance behavior changes.
- Update `README.md` when the module's high-level purpose or setup changes.
- Keep the documented module version aligned with `__manifest__.py` when releasing a versioned build.

## 15. Release checklist

Before packaging a new release:

- [ ] `__manifest__.py` version updated.
- [ ] User Manual reviewed.
- [ ] Developer Manual reviewed.
- [ ] README reviewed.
- [ ] XML views load without errors.
- [ ] Python syntax/imports verified.
- [ ] Frontend assets load.
- [ ] Public category pages work.
- [ ] Search works in Bengali and English.
- [ ] Add to Cart works.
- [ ] Out-of-stock behavior works.
- [ ] Request form works.
- [ ] Request conversion creates a normal sale order.
- [ ] Access rights are correct.
- [ ] No unintended data is exposed publicly.
- [ ] Large-category performance has been checked.


## Version 18.0.4.3.1 — accessibility and performance features

This release adds four customer-facing improvements:
- **Voice Search:** microphone search using the browser Web Speech API, with a graceful text-search fallback.
- **Buy Again:** logged-in customers see products from their recent confirmed/completed orders on the Easy Order home page. No order history is exposed to public visitors.
- **Favorites:** browser-local favorite products with a dedicated Favorites page. The server validates favorite product IDs before displaying current catalog data.
- **Pagination / Load More:** category product lists load an initial page of 24 products and fetch more on demand, reducing initial database work, price calculations, HTML size, and browser rendering.

The user manual and developer manual should be updated whenever these workflows or their implementation change.


## 18.0.4.3.1 code-review corrections

A source-level review corrected category-scoped popularity/search behavior, strengthened cart and request validation, added category recursion protection, added server logging for unexpected cart failures, and aligned Buy Again price rendering with the website price computation.

Recommended next production enhancements:
1. Add automated Odoo HttpCase/TransactionCase coverage for every public JSON/HTTP route.
2. Add a configurable voice-search language instead of hard-coding `bn-BD`.
3. Consider account-synchronized Favorites for multi-device users.
4. Add stock-aware quantity controls and a cart review step for accessibility.
5. Add zero-result search analytics to improve the glossary and catalog organization.

## 14. Version 18.0.4.4.2 — new architecture

### `easy.order.favorite`

A small persistent model stores account-level favorites:

- `partner_id` — customer.
- `product_id` — favorite product variant.
- Unique constraint prevents duplicate partner/product rows.

Guest favorites remain in browser `localStorage`. Logged-in sessions can merge local IDs through `/easy-order/favorites/sync` and remove account favorites through `/easy-order/favorites/remove`.

### Recommendations

`_get_recommended_products()` uses recent confirmed/completed customer orders and co-purchase frequency. Products already purchased are excluded from the recommendation candidate set. Category pages restrict recommendations to their Easy Order category. If there is insufficient history, category recommendations fall back to the existing Popular calculation.

This is deliberately deterministic and Odoo-native. It is not an external machine-learning dependency.

### Recently viewed products

The frontend stores a small list of product IDs/URLs in localStorage when the customer opens a product link. Only the browser stores the history; no personal browsing history is sent to the server by this feature.

### One-tap reorder

`/easy-order/reorder` is a logged-in JSON route. It reads only the current user's latest confirmed/completed sale order, revalidates each product's publication/saleability, and calls Odoo's native `_cart_update()` for each line. It never creates a parallel sale order.

### Simple Checkout

`/easy-order/checkout` is a lightweight summary page. The **Delivery → Payment** button hands control to `/shop/checkout`. Do not implement payment-provider logic inside Easy Order unless there is a compelling requirement; keeping payment in Odoo's native flow avoids duplicated security-sensitive code.

### Order Tracking

`/easy-order/orders` is `auth='user'` and searches only the logged-in customer's sale orders. The controller derives simple timeline flags from order state and `stock.picking` states before rendering. It does not expose another customer's order information.

### Voice Assistant Ordering

`/easy-order/voice/parse` receives transcript text and optionally the current top-level Easy Order code. `_build_voice_items()` extracts simple quantities (including common Bengali/English number words), scopes the catalog when applicable, and uses the existing `_score_product()` matcher to select the strongest product match.

The frontend displays the proposed items and requires an explicit **Add all to cart** action. This is intentionally a safe first-stage implementation. A future external AI provider should return structured product intents and still require the same confirmation step.

### Smarter search

`easy_order_search()` now recognizes common maximum-price phrases and Bengali digits before normal glossary/fuzzy matching. Product terms continue to use the existing scoped SQL prefilter plus Python scoring. If a price-only query is supplied, matching can be based on the price ceiling alone.

### PWA

Two public routes support installability:

- `/easy-order/manifest.json`
- `/easy-order/service-worker.js`

The service worker is deliberately minimal and network-first. It does not intercept non-GET cart/payment mutations. If offline caching becomes more ambitious later, add explicit cache versioning and invalidation rather than caching dynamic checkout/payment responses indiscriminately.

## 15. Security considerations for 18.0.4.4.2

- Account favorites routes use `auth='user'` and server-side partner scoping.
- Reorder reads only the current user's own orders.
- Voice parsing is catalog-read only; it cannot place an order by itself.
- Cart addition continues to validate product/template/variant relationships server-side.
- The simple checkout page does not process payment data.
- Public PWA routes contain no customer/order data.

## 16. Recommended next technical step

For a production deployment, add automated Odoo tests before adding a third-party AI provider. At minimum test:

1. Public visitor cannot retrieve another customer's Buy Again data.
2. Reorder uses only the current customer's latest eligible order.
3. Favorite synchronization cannot create favorites for unpublished products.
4. Voice parsing respects the current Easy Order category scope.
5. Price-filtered search excludes products above the requested ceiling.
6. Order tracking exposes only the logged-in customer's orders.
7. Checkout summary does not bypass Odoo's native payment flow.
8. PWA registration does not intercept POST/payment requests.


### 18.0.4.4.2 QWeb compatibility fix

Order tracking timeline classes now use `t-att-class` instead of nested `t-attf-class` interpolation. This avoids QWeb expression compilation errors in Odoo 18 while preserving the same visual state logic.


### Voice recognition improvement (18.0.4.4.3)
- Voice language can be selected between Bangla (`bn-BD`) and English (`en-US`).
- Recognition now uses interim results and up to five alternatives, then selects the highest-confidence transcript.
- Voice assistant keeps listening feedback and sends only the final transcript to the Odoo catalog matcher.
- The selected language is remembered locally in the browser.
