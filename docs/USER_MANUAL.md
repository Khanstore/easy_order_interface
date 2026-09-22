## 18.0.4.4.2

- Fixed Odoo 18 frontend crash: removed legacy `this._super(...arguments)` calls from `publicWidget` lifecycle methods. Odoo 18 does not provide `_super` on these registry widget instances.

# Easy Order Interface — User Manual

**Module:** Easy Order Interface  
**Version:** 18.0.4.3.1  
**Platform:** Odoo 18  
**Audience:** Sales staff, store operators, and administrators

## 1. What this module does

Easy Order is a simplified storefront designed for customers who may find a normal eCommerce website difficult to use, especially older or low-vision users.

The experience is intentionally simple:

1. Customer opens **`/easy-order`**.
2. Customer chooses a large category tile.
3. Customer opens a subcategory if needed.
4. Customer can search using English, Bengali, or common Romanized Bengali spellings.
5. Customer taps **কার্টে যোগ করুন** to add one item.
6. Customer opens the normal Odoo cart/checkout flow.
7. If the customer cannot find something, they use **খুঁজে পাচ্ছেন না? আমাদের জানান কী চাই →** and describe what they want.

The module uses Odoo's normal `sale.order` cart/checkout engine; it does not create a second shopping-cart system.

## 2. Customer-facing workflow

### Home page

The home page shows the top-level Easy Order categories. Categories are deliberately separate from the normal Website/eCommerce category tree, so staff can organize this interface for the target audience without changing the normal shop navigation.

### Category pages

A category can contain:

- Subcategory tiles.
- Products assigned directly to that category.
- Products inherited from subcategories when **Show products from subcategories too** is enabled.
- A **Popular** row based on confirmed sales history when enough sales data exists.
- A search box scoped to the current top-level section.

### Search

Search supports:

- Exact and partial product-name matches.
- Common spelling mistakes.
- Common Romanized Bengali variations.
- English/Bengali glossary matches for the terms currently configured in the module.
- Category-name matching, with product-name matches receiving stronger ranking.

The search is intentionally forgiving. It should help a customer who remembers what an item is called without knowing the exact catalog title.

### Adding to cart

The customer taps **কার্টে যোগ করুন**. The button changes to a completed state after the server confirms the item was added.

The cart count is updated immediately on the page.

If an item is unavailable under the module's stock rules, the customer sees **স্টকে নেই** instead of a button that will fail.

### Can't find the product

The request form lets the customer enter:

- Name.
- Phone number.
- Optional address.
- One or more requested items.
- Quantity for each item.

Submitting this form does **not** immediately create a sale order. It creates an Easy Order Request for staff review.

## 3. Staff workflow for customer requests

Go to:

**Sales → Easy Order → Requests**

New requests are shown by default.

For each request:

1. Open the request.
2. Review the customer's name, phone, address, and requested items.
3. For each item, click **Suggest** if useful.
4. Review the suggested products.
5. Select the correct product and click **Use this product**.
6. Alternatively, type/search for the real product directly in **Real product**.
7. Confirm the quantity.
8. When every line has a real product, click **Create Order**.
9. Odoo creates a normal `sale.order` and opens it.

A request cannot be converted until every line has a real product.

Once converted, the request becomes **Processed** and keeps a link to the created sale order.

## 4. Managing Easy Order categories

Go to:

**Sales → Easy Order → Categories**

### Create a top-level category

Enter:

- **Internal Name** — staff-facing name.
- **Display Name** — customer-facing name; optional.
- **Image** — optional category image.
- **Code** — optional URL code. If blank, the module generates one for a top-level category.
- **Sequence** — controls display order.
- **Parent Category** — leave blank for a top-level category.

Example:

- Internal Name: `Police Books`
- Display Name: `পুলিশের বই`
- Code: `police-books`

The top-level URL becomes approximately:

`/easy-order/police-books`

### Create a subcategory

Set **Parent Category** to the desired parent. Subcategories do not need a web code.

### Assign products

Open the category's **Products** tab and select the real Odoo product templates that should appear there.

A product can belong to more than one Easy Order category.

### Show products from subcategories too

Enable **Show products from subcategories too** when the parent category should also display products assigned to its descendants.

Use this carefully on very large catalogs because it can increase the number of products rendered on one page.

## 5. Importing categories from the normal shop

Go to:

**Sales → Easy Order → Import from Shop**

Select the normal shop categories to copy.

Important: this is a **one-time copy**, not a synchronization system. Re-running the import can create duplicate Easy Order structures.

After importing, review:

- Names.
- Display names.
- Images.
- Parent/child structure.
- Product assignments.
- Sequence/order.

## 6. Product availability

The module checks the product's saleability/publication status and, when Inventory fields are available, uses stock information to decide whether the Add to Cart action should be shown.

Products configured to continue selling when out of stock are not automatically blocked by this interface.

## 7. Accessibility guidance for staff

To keep the interface useful for older users:

- Prefer short, familiar category names.
- Use clear category images.
- Avoid deep category trees unless necessary.
- Keep products assigned to the most obvious category.
- Use customer-friendly Display Names.
- Avoid abbreviations that customers may not understand.
- Test the interface on a phone as well as a desktop.
- Keep important products near the beginning of a category using category sequence.

## 8. Troubleshooting

### Product does not appear

Check:

1. The product template is published.
2. The product is saleable (`sale_ok`).
3. The product is assigned to the Easy Order category.
4. If viewing a parent category, **Show products from subcategories too** is enabled when appropriate.
5. The product has an orderable variant.

### Search cannot find a product

Try:

- A shorter part of the name.
- Bengali instead of English.
- English instead of Bengali.
- A common Romanized spelling.
- The product's category name.

If it still cannot be found, use the customer request form.

### Customer request cannot create an order

Every request line must have a **Real product** selected. Check that no line is blank.

### Cart count looks wrong

Refresh the page and check the standard Odoo cart. The Easy Order interface intentionally uses Odoo's normal website cart rather than maintaining a separate cart.

## 9. Recommended operating procedure

For a store serving many older customers:

1. Keep the Easy Order home page limited to the most important top-level categories.
2. Put the most commonly ordered products in obvious categories.
3. Review Easy Order Requests at least daily.
4. Add recurring customer language/spelling to the search glossary when a pattern is common.
5. Review search failures before creating new categories.
6. Test the interface after Odoo upgrades or major website changes.


## Version 18.0.4.3.1 — accessibility and performance features

This release adds four customer-facing improvements:
- **Voice Search:** microphone search using the browser Web Speech API, with a graceful text-search fallback.
- **Buy Again:** logged-in customers see products from their recent confirmed/completed orders on the Easy Order home page. No order history is exposed to public visitors.
- **Favorites:** browser-local favorite products with a dedicated Favorites page. The server validates favorite product IDs before displaying current catalog data.
- **Pagination / Load More:** category product lists load an initial page of 24 products and fetch more on demand, reducing initial database work, price calculations, HTML size, and browser rendering.

The user manual and developer manual should be updated whenever these workflows or their implementation change.


## 18.0.4.3.1 maintenance notes

The latest maintenance release improves reliability: Popular products are calculated across the full category, search remains inside the current Easy Order section, invalid products are blocked from cart/order creation, and invalid request quantities are no longer silently changed to 1.

## Version 18.0.4.4.2 — ordering assistant and mobile improvements

This release adds:

- **Smart recommendations:** customer-specific co-purchase suggestions when order history exists, with popular products as a fallback.
- **Recently viewed products:** products opened from Easy Order are remembered on the same device and shown on the home page.
- **One-tap reorder:** logged-in customers can add the latest confirmed/completed order's available products to the current cart in one action.
- **Simple Checkout:** an Easy Order checkout summary provides a short Cart → Delivery → Payment → Confirm path, while the final delivery/payment processing remains Odoo's native secure checkout.
- **Order Tracking:** logged-in customers get a simple order timeline based on the Odoo sale order and delivery status.
- **Voice Assistant Ordering:** customers can say multiple requested products and quantities; Easy Order matches them against the catalog and asks for a tap before adding anything to the cart.
- **Smarter search:** price phrases such as “under 1000” can be used as a price filter alongside product terms.
- **Synchronized Favorites:** logged-in customers can merge local browser favorites into their Odoo account; guests continue using local favorites.
- **PWA support:** Easy Order can be installed as an app-like experience on supported browsers, with a network-first service worker fallback.

### Important voice-ordering note

The first implementation uses browser speech recognition plus Odoo's local catalog matching. It does **not** send a customer's voice recording to an external AI provider. Every matched item is shown for confirmation before it is added to the cart.

### Important checkout note

Easy Order does not replace Odoo's payment/checkout security. The simplified screen is a clear summary and hand-off; delivery addresses, delivery methods, payment providers, and final order confirmation remain under the standard Odoo checkout flow.


### 18.0.4.4.2

Order Tracking rendering compatibility was fixed for Odoo 18.


### Voice recognition improvement (18.0.4.4.3)
- Voice language can be selected between Bangla (`bn-BD`) and English (`en-US`).
- Recognition now uses interim results and up to five alternatives, then selects the highest-confidence transcript.
- Voice assistant keeps listening feedback and sends only the final transcript to the Odoo catalog matcher.
- The selected language is remembered locally in the browser.
