# REST API

Base URL: `/api/`. JSON only. The generated OpenAPI 3 schema is the source of truth:

- `GET /api/schema/` — OpenAPI YAML/JSON
- `GET /api/docs/` — Swagger UI
- `GET /api/redoc/` — ReDoc

Status legend: ✅ implemented & tested · 🔜 planned (phase)

## Conventions
- Auth: `Authorization: Bearer <access>`. Access token lifetime is 15 min; the refresh token rotates.
- Pagination: `?page=&page_size=` → `{count, next, previous, results}`.
- Errors: consistent envelope
  ```json
  { "error": { "code": "validation_error", "message": "Invalid input.", "details": { "field": ["msg"] } }, "request_id": "..." }
  ```
- Every response carries an `X-Request-ID` header, which is echoed from the request when one is supplied.
- Rate limits return `429` with `code: "throttled"`.

## System
| Method | Path | Auth | Status |
|---|---|---|---|
| GET | `/api/health/` | public | ✅ returns app, version, database status |

## Auth — `/api/auth/` (Phase 3)
| Method | Path | Notes |
|---|---|---|
| POST | `register/` | email, phone, password, full_name → user + tokens 🔜 |
| POST | `login/` | email/phone + password → access, refresh 🔜 |
| POST | `token/refresh/` | rotate refresh 🔜 |
| POST | `logout/` | blacklist refresh 🔜 |
| POST | `password/forgot/` · `password/reset/` | token emailed via notification service 🔜 |
| GET/PATCH | `me/` | profile 🔜 |

## Users & Addresses — `/api/users/` (Phase 3)
`GET/POST /api/users/me/addresses/`, `GET/PATCH/DELETE /api/users/me/addresses/{id}/`, `POST …/{id}/set-default/` 🔜

## Catalog (Phase 4)
| Path | Notes |
|---|---|
| `GET /api/categories/` | tree 🔜 |
| `GET /api/categories/{slug}/` | 🔜 |
| `GET /api/brands/` | 🔜 |
| `GET /api/products/` | filters: category, brand, price_min/max, in_stock, spec__<key>, rating; ordering: price, -price, -created_at, -rating, popularity 🔜 |
| `GET /api/products/{slug}/` | detail with variants, specs, images, stock summary, ETA for the user's address 🔜 |
| `GET /api/products/compare/?ids=` | 🔜 |
| `GET /api/search/?q=` | full-text + trigram typo tolerance 🔜 |
| `GET /api/search/suggest/?q=` | 🔜 |

## Shopping (Phase 6)
`/api/cart/` (GET, POST items, PATCH/DELETE items/{id}, POST apply-coupon, DELETE coupon) · `/api/wishlist/` · `/api/coupons/validate/` 🔜

## Orders (Phase 7)
`POST /api/orders/checkout/preview/` (totals + delivery eligibility + ETA) · `POST /api/orders/` · `GET /api/orders/` · `GET /api/orders/{public_id}/` · `POST …/cancel/` · `POST …/return/` · `POST …/reorder/` · `GET …/tracking/` 🔜

## Payments (Phase 8)
`POST /api/payments/razorpay/order/` · `POST /api/payments/razorpay/verify/` · `POST /api/payments/webhooks/razorpay/` (signature verified) · `GET /api/payments/{id}/refunds/` 🔜

## Inventory & Stores — staff/admin (Phase 7, 9)
`/api/inventory/` · `/api/inventory/{id}/adjust/` · `/api/inventory/movements/` · `/api/stores/` · `/api/stores/{id}/zones/` · `POST /api/delivery/eta/` 🔜

## Delivery partner — `/api/delivery/` (Phase 10)
`GET/PATCH me/` · `POST me/availability/` · `GET assignments/` · `GET assignments/{id}/` · `POST assignments/{id}/pickup/` · `POST …/out-for-delivery/` · `POST …/deliver/` (OTP + proof image) · `GET earnings/` 🔜

## Reviews (Phase 4/19)
`GET/POST /api/products/{slug}/reviews/` · `PATCH/DELETE /api/reviews/{id}/` · `GET /api/products/{slug}/reviews/summary/` (AI summary of real reviews) 🔜

## Notifications & Support (Phase 20)
`GET /api/notifications/` · `POST /api/notifications/{id}/read/` · `POST /api/notifications/read-all/` · `/api/support/conversations/` · `POST /api/support/webhooks/whatsapp/` (signature verified) 🔜

## AI — `/api/ai/` (Phase 12–19)
| Path | Notes |
|---|---|
| `POST assistant/` | `{conversation_id?, message, language?}` → `{reply, intent, products:[catalog cards], follow_up_questions}` 🔜 |
| `POST search/` | natural-language → structured filters + results 🔜 |
| `POST image-search/` | multipart image → `{identification:{category, attributes, confidence}, matches, alternatives}` 🔜 |
| `POST voice/` | audio → transcript → assistant response 🔜 |
| `POST projects/` · `POST projects/{id}/answer/` · `POST projects/{id}/add-to-cart/` | project builder 🔜 |
| `POST calculators/{type}/` | paint, tiles, pipe, wire, screws, cement, adhesive (deterministic) 🔜 |
| `POST compatibility/` | `{variant_ids:[...]}` → verdict per pair 🔜 |
| `GET smart-cart/` | suggestions for current cart 🔜 |
| `POST budget/` | budget/balanced/premium options with reasons 🔜 |
| `GET recommendations/` | respects `personalization_opt_in` 🔜 |

## Admin — `/api/admin/` (Phase 11, role=admin/store_staff)
`dashboard/` · `products/` (CRUD, images, specs, variants) · `categories/` · `brands/` · `orders/` (+ `transition/`) · `inventory/` · `customers/` · `delivery-partners/` · `coupons/` · `offers/` · `bundles/` (approve AI drafts) · `analytics/*` · `ai/business-assistant/` · `audit-log/` 🔜
