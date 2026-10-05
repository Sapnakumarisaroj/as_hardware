# Commerce parity requirements

Added 2026-10-05 as a core product requirement. A leading Indian construction/interior-materials quick-commerce
store (home-run.co) is used as a **feature reference only**: we match and improve on its features (fast local
delivery, PIN-based delivery, deals, bulk pricing, free-delivery rules, cashback, pay on delivery, product options,
construction/hardware departments) and connect them to our AI.

We do **not** copy its name, logo, images, product photos, marketing text, source code, assets or visual design.
Brand, UI, text and images are our own.

Target: hardware/construction e-commerce + fast delivery + bulk buying + offers + local fulfilment + AI assistant,
semantic, image and voice search, Project Builder, quantity, compatibility, smart cart and business AI.

## Rules that apply to every phase from now on
1. **One pricing engine.** Every price (list, tier, offer, coupon, free delivery, credits) is calculated in the
   backend by `orders.pricing` + `offers.engine`. The frontend and the AI only display server numbers. Prices sent
   by a client are never used.
2. **Catalogue structure comes from the database.** Departments, categories, subcategories, option types,
   collections and homepage sections are admin data. No category names in frontend components; the taxonomy below
   is seed data.
3. **No hardcoded delivery promise.** "60 minutes" is never a constant: fast delivery is shown only when the Phase 9
   engine says so for that PIN/address (zone, store stock, opening hours, preparation, rider availability, ETA vs.
   the zone's cutoff). Otherwise standard delivery with its window.
4. **No fake money.** Cashback and credits exist only as ledger entries with a source and a reference. No seeded
   balances, no invented ratings, counts or "x bought today".
5. **Honest conditions.** MRP, price, savings, GST, delivery fee, stock, returnability, payment options, bulk tiers
   and offer conditions are shown, not hidden.
6. **Sections only with data.** A homepage section, badge or filter with nothing behind it is not shown.
7. **Free first.** No paid service is added for these features.
8. **Completed phases are not rewritten.** Gaps are closed with backward-compatible additions (new tables, new
   optional fields, additive API fields) in the phases below.

## Gaps in completed phases (1–14)
| Area | What exists | Gap | Closed in |
|---|---|---|---|
| Pricing (2, 5, 6) | One server path: `line_from_variant` → `price_lines` (offers → coupon → GST → delivery fee) used by cart, checkout, orders; `OrderItem.unit_price` snapshot; returns refund what was paid | No quantity tiers: the unit price is always `variant.price` | 15 (tier lookup inside `line_from_variant`; returns need no change because they use the snapshot) |
| Categories (2, 4) | Two-level tree (category › subcategory), `sort_order`, image, counts | Three levels needed (department › category › subcategory); the model refuses a third level | 15 (allow depth 3, products keep `category` + `subcategory`; navigation by department) |
| Product options (2, 4) | `ProductVariant.attributes` JSON, variant selector, `?variant=` | No option types/order per category; variant attributes not filterable (TASKS known limitation) | 15 (schema) + 16 (filters/UI) |
| Merchandising (4) | `is_featured`, bestseller by units sold, newest by `created_at` | No "new launch" window, no curated collections ("Deals of the week", "Construction essentials", "Bulk buying") | 15 |
| Offers (6) | Percent/fixed, cap, minimum spend, dates, product/category targets, priority, one coupon per order | No quantity-based, first-order, festival/campaign, free-delivery or cashback offer types; no usage/per-customer limits on offers (TASKS known limitation) | 15 (cashback offers in 17) |
| Free delivery (5, 9) | Global `FREE_DELIVERY_MIN_ORDER` + per-zone `free_delivery_min_order`; checkout returns `amount_to_free_delivery` | No date-bound rules, no product/category eligibility | 15 |
| Cash on delivery (5, 8, 10) | COD is a first-class method; cash collected by the rider, handover, manual COD refunds | No COD eligibility rules or order-value limit (decided: ₹10,000 maximum, admin-configurable, no exclusions initially) | 15 |
| Loyalty (—) | `Payment.Method.WALLET` enum value only | No ledger, rules or wallet | 17 |
| Fast delivery (9) | Zone cutoff, ETA engine, fast-store stock filter, PIN check in the header | Listing/card fast badge is based on stock at fast stores, not on the selected PIN | 16 |
| Product card / page (4, 6, 9) | Image, name, brand, rating, MRP/price/discount, offer badge, stock, delivery estimate, specs, reviews, related | Bulk table/indicator, options count, quantity stepper on card, free-delivery message, payment options, GST note, return-policy text, accessories, Buy Now | 16 |
| Homepage (4, 6) | Hero, categories, offers, best sellers, featured, fast delivery, recently added, recommended; empty sections hidden | Deals of the week, department rails, bulk buying, AI entry points, recently viewed | 16 |
| Search (4, 13) | Hybrid keyword + related words + embeddings, Hindi/Hinglish, spec filters | Query words that mean a spec or a use ("for plastering", "53 grade", "50 kg") are not turned into filters | 16 |
| AI assistant (12, 14) | Grounded catalogue answers, budget, add to cart via the cart API | Quantity estimates, tier/offer/free-delivery awareness | Tiers reach the assistant automatically in 15 (cart API); estimates in 19–22 |
| Admin dashboard (11) | Categories, products, variants, prices, offers, coupons, inventory, stores, zones, customers, orders, riders | Tiers, option types, collections, free-delivery rules, COD rules, cashback rules | 15, 17 |

## Requirement → phase
| Requirement | Phase |
|---|---|
| 60-minute eligible delivery, PIN/location, fast indicator, standard fallback | 9 ✅ (engine) · 16 (PIN-aware indicators everywhere) |
| Category shopping, departments/categories/subcategories from the DB | 4 ✅ · 15 (3 levels, seed taxonomy) · 16 (landing pages) |
| Deals of the week, new launches, featured, best sellers, collections | 15 (data) · 16 (UI) |
| Offers: percent, fixed, category, product, minimum spend, dates | 6 ✅ |
| Offers: quantity-based, first-order, festival, free-delivery, usage limits | 15 |
| Offers: cashback/credit | 17 |
| Bulk / quantity pricing (cart, checkout, orders, returns, admin) | 15 |
| Product options (cement brand/grade/bag size, plywood thickness/size, wire length/cross-section, paint colour/pack) | 15 (data) · 16 (UI, filters) |
| Free-delivery rules (threshold, zone, products/categories, dates, "Add ₹X more") | 15 |
| Pay on delivery: eligibility, limits | 15 · collection, rider confirmation, handover, refunds: 8/10 ✅ |
| Online payment | 8 ✅ |
| Cashback / wallet / promotional credits / referral / points | 17 |
| Product card, product page, category landing, filters | 16 |
| Homepage sections (19 listed) | 16 (AI entry points link to 12/14 now and 19/22 when built) |
| Recently viewed | 16 |
| Recommended accessories | 16 (admin links) · 21 (rule-based compatibility) |
| Search: keyword + synonyms + Hindi/Hinglish + meaning | 13 ✅ |
| Search: specification/category/brand/availability understanding | 16 |
| Voice shopping | 18 |
| Project-based shopping, Project Builder | 19 |
| Quantity AI ("cement for 500 sq ft plastering") | 20 |
| Compatibility AI | 21 |
| Smart Cart (missing items, cheaper tier, offers, free-delivery gap, accessories) | 22 |
| Business AI, offer/bulk/cashback analytics | 24 |
| Admin for all of the above | 11 ✅ (existing) · 15 · 17 |

## Loyalty credit rules (decided 2026-10-05, Phase 17)
- Credits are never paid out as cash.
- Credits pay at most 20 % of an order (after offers and coupon; configurable).
- Each credit entry expires 90 days after it becomes available (configurable); oldest-expiring credits are used first.
- When returned items are refunded, the credits used on those items are restored in proportion, keeping the original
  entry's expiry; credits that have already expired by then are not restored.
- Balance = sum of ledger entries; nothing is seeded or adjusted without a ledger entry and a reference.

## Seed taxonomy (data, not code)
Loaded by `seed_demo_data` (demo) and editable in the dashboard. Department › categories:
- **Civil & Interiors**: Cement (Grey Cement, White Cement), Tiling (Tiles, tile adhesive/grout), Plywood, MDF,
  HDHMR, Adhesives, Waterproofing, Painting, Wall care
- **Electrical**: Wires, Cables, MCB, Distribution Boards, Switches, Sockets, Electrical Conduits, Lighting, Fans
- **Plumbing, Sanitary & Bath**: CPVC Pipes, PVC Pipes, Fittings, Taps, Sanitary fittings, Bath fittings, Water
  tanks, Valves
- **Furniture & Architectural Hardware**: Hinges, Channels, Handles, Kitchen systems, Wardrobe fittings, Bed
  fittings, Door locks, Glass-door hardware
- **Tools**: Power tools, Hand tools, Drill machines, Drill bits, Grinders, Measuring tools, Safety equipment
- **Hardware & Appliances**: CCTV, Home appliances, Power backup, General hardware, Workwear

Brand names in demo data stay generic "(Demo)" brands; real brands are entered by the owner.

## Bulk pricing behaviour (Phase 15)
- Tiers per variant, e.g. 1–9 → ₹450, 10+ → ₹415, 30+ → ₹405, 50+ → ₹395. The base tier is `variant.price`.
- The unit price for a line is the tier reached by that line's quantity. Offers and the coupon then apply to the
  tiered amount; GST on the net amount (unchanged order of operations).
- Cart, checkout preview and order placement re-price on every request; a tier change between preview and order
  gives the existing 409 `totals_changed`.
- `OrderItem` keeps `unit_price` (tiered) and the tier's minimum quantity; returns refund what was paid for those
  units (existing return maths).
- APIs show `price_tiers`, `bulk_available`, the applied tier and the next tier ("Add 3 more for ₹405/unit").
- Admin validation: quantities strictly ascending, prices non-increasing, every price ≤ MRP and > 0.

## AI integration
The AI never prices anything itself. It calls the same cart, checkout-preview and delivery APIs as the website, so:
- "I need 20 bags" → the assistant's add-to-cart lands in the 10+ tier, and the reply shows the server's tier, total,
  stock and delivery estimate (works once Phase 15 is in, since the assistant uses the cart API).
- "Cement for 500 sq ft plastering" → Phase 20 asks for missing inputs (thickness, mix), estimates bags with a stated
  formula, picks real products via Phase 13/16 search, then reads tier, offers and delivery from the server.
- Smart Cart (Phase 22) reads `next_tier`, `offers.missed`, `amount_to_free_delivery` and compatibility results from
  the server; it adds nothing the customer did not accept.
