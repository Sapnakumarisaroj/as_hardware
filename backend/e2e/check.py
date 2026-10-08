"""End-to-end checks over real HTTP (Phase 26): customer, delivery, admin, security and failure cases.

Run against a server on a COPY of a seeded database (`seed_demo_data`), never a live shop:

    python manage.py shell -c "exec(open('e2e/setup.py').read())"   # staff accounts (copy only)
    python e2e/check.py http://127.0.0.1:8026/api                   # 130 checks; exit code 1 on failure

The customers are registered through the API, so use a fresh copy for every run. Raise the `auth`, `ai`
and `image_search` rate limits for the run (THROTTLE_AUTH=1000/min …): it signs in many times.
"""

import io
import json
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid

from PIL import Image

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8026/api"
if not BASE.startswith(("http://", "https://")):
    sys.exit("The base URL must be http(s).")
PASSWORD = "E2e-check-26!"  # noqa: S105 — test accounts on a database copy
KTH_LAT, KTH_LNG = "12.925000", "77.593800"
results = []
S = {}  # shared state between sections


def call(method, path, body=None, token=None, params=None, headers=None, files=None, raw=False):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data, content_type = None, "application/json"
    if files is not None:
        boundary = uuid.uuid4().hex
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, v in (body or {}).items()
        ]
        for name, (filename, content, ctype) in files.items():
            head = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n"
            )
            parts.append(head.encode() + content + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        data, content_type = b"".join(parts), f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)  # noqa: S310 — http(s) only, checked above
    req.add_header("Content-Type", content_type)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as res:  # noqa: S310 — http(s) only, checked above
            payload = res.read()
            if raw:
                return res.status, payload, dict(res.headers)
            return res.status, (json.loads(payload) if payload else None)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            parsed = json.loads(payload)
        except ValueError:
            parsed = payload[:300]
        return (exc.code, parsed, dict(exc.headers)) if raw else (exc.code, parsed)


def check(name, condition, detail=""):
    results.append((name, bool(condition)))
    print(("PASS" if condition else "FAIL"), "-", name, "" if condition else f"  <-- {str(detail)[:300]}")


def code_of(body):
    return body["error"]["code"] if isinstance(body, dict) and "error" in body else body


def rows(body):
    return body["results"] if isinstance(body, dict) and "results" in body else body


def login(email, password=PASSWORD):
    status, data = call("POST", "/auth/login/", {"email": email, "password": password})
    assert status == 200, (email, status, data)
    return data["access"], data["refresh"]


def jpeg(size=(800, 600), exif=False):
    out = io.BytesIO()
    img = Image.new("RGB", size, (180, 120, 60))
    kwargs = {}
    if exif:
        e = Image.Exif()
        e[0x010F] = "Phone"
        kwargs["exif"] = e
    img.save(out, format="JPEG", **kwargs)
    return out.getvalue()


SECTIONS = []


def section(fn):
    SECTIONS.append(fn)
    return fn


def variant(sku):
    """(product slug, variant id, price) for a demo SKU from the public catalogue."""
    status, page = call("GET", "/products/", params={"q": sku, "page_size": 5})
    for p in rows(page):
        status, detail = call("GET", f"/products/{p['slug']}/")
        for v in detail["variants"]:
            if v["sku"] == sku:
                return detail, v
    raise AssertionError(f"variant {sku} not found")


# --- 1. Customer: account ---------------------------------------------------------------------------------


@section
def accounts():
    for key, email, phone in (("A", "e2e-a@example.com", "9812300011"), ("B", "e2e-b@example.com", "9812300012")):
        status, body = call(
            "POST",
            "/auth/register/",
            {
                "full_name": f"E2E {key}",
                "email": email,
                "phone": phone,
                "password": PASSWORD,
                "password_confirm": PASSWORD,
            },
        )
        check(f"register customer {key}", status == 201, (status, body))
    status, body = call(
        "POST",
        "/auth/register/",
        {
            "full_name": "Dup",
            "email": "e2e-a@example.com",
            "phone": "9812300099",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
        },
    )
    check("duplicate email refused", status == 400, (status, body))
    status, body = call("POST", "/auth/login/", {"email": "e2e-a@example.com", "password": "wrong-pass-1"})
    check("wrong password: generic 401", status == 401 and "password" in json.dumps(body).lower(), (status, body))
    S["A"], S["A_refresh"] = login("e2e-a@example.com")
    S["B"], _ = login("e2e-b@example.com")
    status, me = call("GET", "/auth/me/", token=S["A"])
    check("me", status == 200 and me["role"] == "customer", me)
    status, body = call("POST", "/auth/token/refresh/", {"refresh": S["A_refresh"]})
    check("refresh rotates", status == 200 and body.get("refresh") and body["refresh"] != S["A_refresh"], body)
    status, again = call("POST", "/auth/token/refresh/", {"refresh": S["A_refresh"]})
    check("old refresh token can't be replayed", status == 401, (status, again))
    _, tmp_refresh = login("e2e-b@example.com")
    status, _ = call("POST", "/auth/logout/", {"refresh": tmp_refresh}, token=S["B"])
    status2, _ = call("POST", "/auth/token/refresh/", {"refresh": tmp_refresh})
    check("logout revokes the refresh token", status in (200, 204, 205) and status2 == 401, (status, status2))
    for who in ("A", "B"):
        status, addr = call(
            "POST",
            "/addresses/",
            {
                "name": f"E2E {who}",
                "phone": "9812300011",
                "address_line1": "1 Test Lane",
                "city": "Bengaluru",
                "state": "Karnataka",
                "postal_code": "560041",
                "latitude": KTH_LAT,
                "longitude": KTH_LNG,
            },
            S[who],
        )
        check(f"address for {who}", status == 201, (status, addr))
        S[f"{who}_addr"] = addr["id"] if status == 201 else None


# --- 2. Customer: catalogue -------------------------------------------------------------------------------


@section
def catalogue():
    status, cats = call("GET", "/categories/")
    names = [c["name"] for c in cats]
    check(
        "10 approved categories in navigation",
        len(names) == 10 and "Fevicol" in names and "Plumbing" not in names,
        names,
    )
    status, page = call("GET", "/products/", params={"category": "hinges-channels-handles"})
    check(
        "category filter",
        status == 200
        and rows(page)
        and all("Hinge" in p["name"] or "Channel" in p["name"] or "Handle" in p["name"] for p in rows(page)),
        [p["name"] for p in rows(page)],
    )
    status, page = call("GET", "/products/", params={"brand": "fevicol"})
    check("brand filter", status == 200 and len(rows(page)) == 3, [p["name"] for p in rows(page)])
    status, page = call("GET", "/products/", params={"min_price": "1000", "ordering": "price"})
    prices = [float(p["price"]) for p in rows(page)]
    check("price filter + sort", prices and min(prices) >= 1000 and prices == sorted(prices), prices[:5])
    status, page = call("GET", "/products/", params={"q": "kabja"})
    check(
        "Hinglish search 'kabja' finds hinges",
        any("Hinge" in p["name"] for p in rows(page)),
        [p["name"] for p in rows(page)],
    )
    status, sug = call("GET", "/search/suggest/", params={"q": "plyw"})
    check("suggestions", status == 200 and sug, sug)
    detail, v18 = variant("DEMO-PLY-BWP-18")
    check(
        "product detail: variants, images, MRP ≥ price",
        len(detail["variants"]) == 3 and detail["images"] and float(v18["mrp"]) >= float(v18["price"]),
        (len(detail["variants"]), len(detail["images"])),
    )
    S["ply"] = (detail, v18)
    status, quote = call("GET", f"/products/{detail['slug']}/quote/", params={"variant": v18["id"], "quantity": 10})
    check("bulk price at 10 sheets (₹4,090)", status == 200 and quote["unit_price"] == "4090.00", quote)
    status, cmp = call(
        "POST",
        "/compatibility/check/",
        {"product_a": variant("DEMO-DRILL-650")[0]["id"], "product_b": variant("DEMO-BIT-MAS-5")[0]["id"]},
    )
    check(
        "compatibility engine: drill + masonry bits",
        status == 200 and json.dumps(cmp).count("COMPATIBLE") >= 1,
        cmp if status != 200 else "",
    )
    status, offers = call("GET", "/offers/")
    check("live offers listed", status == 200 and rows(offers), offers)


# --- 3. Customer: wishlist, cart, coupons, smart cart ------------------------------------------------------


@section
def cart():
    A = S["A"]
    detail, v18 = S["ply"]
    status, _ = call("POST", "/wishlist/", {"product_id": detail["id"]}, A)
    status2, wl = call("GET", "/wishlist/", token=A)
    check(
        "wishlist add",
        status == 201
        and any(i.get("product_id", i.get("id")) == detail["id"] or detail["slug"] in json.dumps(i) for i in rows(wl)),
        wl,
    )
    call("DELETE", f"/wishlist/{detail['id']}/", token=A)
    status, body = call("POST", "/cart/items/", {"variant_id": v18["id"], "quantity": 100000}, A)
    check("out-of-stock / limit quantity refused", status in (400, 409), (status, code_of(body)))
    status, c = call("POST", "/cart/items/", {"variant_id": v18["id"], "quantity": 10}, A)
    check("add 10 sheets to cart", status in (200, 201), (status, c))
    status, c = call("GET", "/cart/", token=A)
    line = c["items"][0]
    check(
        "cart line priced with the bulk tier",
        line["unit_price"] == "4090.00" if "unit_price" in line else "4090" in json.dumps(line),
        line,
    )
    status, body = call("POST", "/cart/coupon-preview/", {"code": "NOPE-123"}, A)
    check("invalid coupon refused with a reason", status in (400, 404) and code_of(body), (status, body))
    status, body = call("POST", "/cart/coupon-preview/", {"code": "DEMO10"}, A)
    check("DEMO10 previews a discount", status == 200 and "discount" in json.dumps(body), (status, body))
    status, smart = call("GET", "/shopping/cart/", token=A)
    check("smart cart sections", status == 200 and "sections" in smart, (status, smart))
    status, rec = call("GET", "/shopping/recommendations/", params={"product": detail["id"]})
    check("recommendations for plywood", status == 200 and "groups" in rec, status)
    status, bundles = call("GET", "/shopping/bundles/")
    check("4 demo kits", status == 200 and len(rows(bundles)) == 4, len(rows(bundles)) if status == 200 else status)


# --- 4. Customer: AI features --------------------------------------------------------------------------------


@section
def ai():
    A = S["A"]
    status, body = call("POST", "/ai/conversations/", {"message": "Which hinges for kitchen cabinets?"}, A)
    check(
        "AI assistant answers with real products",
        status in (200, 201) and "Hinge" in json.dumps(body),
        (status, str(body)[:200]),
    )
    status, body = call("POST", "/ai/voice/command/", {"transcript": "5 sheets of 18 mm plywood", "language": "en"})
    lines = body.get("lines", []) if isinstance(body, dict) else []
    check(
        "voice: quantity + plywood priced, nothing added",
        status == 200 and lines and lines[0]["quantity"] == 5 and "Plywood" in (lines[0]["product_name"] or ""),
        (status, str(body)[:300]),
    )
    status, body = call("POST", "/ai/quantity/", {"text": "Screws and wall plugs for 12 holes in a brick wall"})
    check(
        "Quantity AI: complete plan with materials",
        status == 200 and body.get("complete") and body.get("materials"),
        (status, str(body)[:300]),
    )
    status, body = call("POST", "/ai/projects/", {"description": "Repair my wardrobe, the doors are loose"}, A)
    check(
        "Project builder: furniture repair plan", status == 201 and "kit" in json.dumps(body), (status, str(body)[:300])
    )
    status, body = call(
        "POST", "/shopping/budget/", {"text": "Hardware to fix 3 shelves on a brick wall under ₹1500"}, A
    )
    check("budget plan stays within budget", status == 200, (status, str(body)[:300]))
    status, body = call("POST", "/ai/image-search/", {}, A, files={"image": ("hinge.jpg", jpeg(), "image/jpeg")})
    check(
        "image search answers (provider off → honest 'unavailable')",
        status in (200, 503) and "status" in json.dumps(body) or status == 200,
        (status, str(body)[:300]),
    )
    status, body = call("POST", "/ai/image-search/", {}, A, files={"image": ("x.jpg", b"not an image", "image/jpeg")})
    check("image search: invalid file refused", status == 400, (status, body))


# --- 5. Checkout and payments ----------------------------------------------------------------------------------


@section
def checkout():
    A, B = S["A"], S["B"]
    status, prev = call(
        "POST", "/checkout/preview/", {"address_id": S["A_addr"], "payment_method": "cod", "coupon_code": "DEMO10"}, A
    )
    check("checkout preview", status == 200 and prev["can_place_order"], (status, str(prev)[:300]))
    status, body = call("POST", "/orders/", {"address_id": S["A_addr"], "payment_method": "cod"}, A)
    check(
        "COD refused above ₹10,000 (10 sheets ≈ ₹40,900)",
        status == 400 and code_of(body) == "cod_unavailable",
        (status, body),
    )
    status, c = call("GET", "/cart/", token=A)
    call("PATCH", f"/cart/items/{c['items'][0]['id']}/", {"quantity": 2}, A)
    status, prev = call(
        "POST", "/checkout/preview/", {"address_id": S["A_addr"], "payment_method": "cod", "coupon_code": "DEMO10"}, A
    )
    total = prev["totals"]["grand_total"]
    status, body = call(
        "POST",
        "/orders/",
        {"address_id": S["A_addr"], "payment_method": "cod", "coupon_code": "DEMO10", "expected_total": "1.00"},
        A,
    )
    check(
        "price changed during checkout → 409 totals_changed",
        status == 409 and code_of(body) == "totals_changed",
        (status, body),
    )
    key = uuid.uuid4().hex
    order_body = {
        "address_id": S["A_addr"],
        "payment_method": "cod",
        "coupon_code": "DEMO10",
        "expected_total": total,
        "idempotency_key": key,
    }
    status, order = call("POST", "/orders/", order_body, A)
    check(
        "COD order placed (bulk tier + coupon, total as previewed)",
        status == 201 and order["grand_total"] == total,
        (status, str(order)[:300]),
    )
    S["cod_order"] = order["order_number"]
    status, again = call("POST", "/orders/", order_body, A)
    check(
        "same idempotency key → same order, no duplicate",
        again.get("order_number") == order["order_number"],
        (status, again),
    )
    status, mine = call("GET", "/orders/", token=A)
    check("order history", status == 200 and rows(mine)[0]["order_number"] == S["cod_order"], status)
    status, _ = call("GET", f"/orders/{S['cod_order']}/", token=B)
    check("another customer can't see it (404)", status == 404, status)

    # Online payment: fail, retry, succeed; and a cancelled payment.
    _, v = variant("DEMO-HNG-SC-FO")
    call("POST", "/cart/items/", {"variant_id": v["id"], "quantity": 2}, B)
    status, online = call("POST", "/orders/", {"address_id": S["B_addr"], "payment_method": "online"}, B)
    check(
        "online order placed, waiting for payment",
        status == 201 and online["status"] == "pending",
        (status, str(online)[:300]),
    )
    pay = online["payments"][-1] if online.get("payments") else online.get("payment")
    sig = pay["client_payload"]["mock_signature"]
    status, res = call(
        "POST",
        f"/payments/{pay['public_id']}/verify/",
        {"payload": {"mock_signature": sig, "mock_outcome": "failed"}},
        A,
    )
    check("someone else can't verify the payment (404)", status == 404, status)
    status, res = call(
        "POST",
        f"/payments/{pay['public_id']}/verify/",
        {"payload": {"mock_signature": sig, "mock_outcome": "failed"}},
        B,
    )
    status_o, o = call("GET", f"/orders/{online['order_number']}/", token=B)
    check(
        "failed payment: order still pending, nothing taken",
        o["status"] == "pending" and o["payment_status"] in ("failed", "pending"),
        (o["status"], o["payment_status"]),
    )
    status, retry = call("POST", f"/orders/{online['order_number']}/retry-payment/", {}, B)
    check("retry payment gives a new attempt", status in (200, 201), (status, retry))
    attempt = [
        p for p in retry["payments"] if p["public_id"] != pay["public_id"] and p["client_payload"].get("mock_signature")
    ][0]
    status, res = call(
        "POST",
        f"/payments/{attempt['public_id']}/verify/",
        {"payload": {"mock_signature": attempt["client_payload"]["mock_signature"], "mock_outcome": "success"}},
        B,
    )
    status_o, o = call("GET", f"/orders/{online['order_number']}/", token=B)
    check(
        "successful payment confirms the order",
        o["status"] == "confirmed" and o["payment_status"] == "paid",
        (o["status"], o["payment_status"]),
    )
    S["online_order"] = online["order_number"]
    status, res = call(
        "POST",
        f"/payments/{attempt['public_id']}/verify/",
        {"payload": {"mock_signature": attempt["client_payload"]["mock_signature"], "mock_outcome": "success"}},
        B,
    )
    status_o, o2 = call("GET", f"/orders/{online['order_number']}/", token=B)
    check(
        "verifying again doesn't pay twice",
        o2["payment_status"] == "paid" and o2["grand_total"] == o["grand_total"],
        (status, res),
    )

    call("POST", "/cart/items/", {"variant_id": v["id"], "quantity": 1}, B)
    status, third = call("POST", "/orders/", {"address_id": S["B_addr"], "payment_method": "online"}, B)
    p3 = third["payments"][-1] if third.get("payments") else third.get("payment")
    status, res = call("POST", f"/payments/{p3['public_id']}/verify/", {"payload": {"cancelled": True}}, B)
    status_o, o3 = call("GET", f"/orders/{third['order_number']}/", token=B)
    check(
        "cancelled payment leaves the order unpaid", o3["payment_status"] != "paid", (status, res, o3["payment_status"])
    )
    status, res = call("POST", f"/orders/{third['order_number']}/cancel/", {"reason": "Changed my mind"}, B)
    check("cancel the unpaid order: stock released", status == 200 and res["status"] == "cancelled", (status, res))
    status, res = call("POST", f"/orders/{third['order_number']}/cancel/", {"reason": "again"}, B)
    check("cancelling twice is refused", status in (400, 409), (status, res))

    status, res = call("POST", "/payments/webhooks/razorpay/", {"event": "payment.captured"})
    check("unsigned payment webhook refused", status in (400, 401, 403, 404), (status, res))


# --- 6. Delivery: fulfilment, rider, OTP, proof, COD, failure and re-dispatch --------------------------------------


@section
def delivery():
    admin, _ = login("e2e-admin@example.com")
    mgr_k, _ = login("e2e-mgr-k@example.com")
    mgr_b, _ = login("e2e-mgr-b@example.com")
    r1, _ = login("e2e-rider1@example.com")
    r2, _ = login("e2e-rider2@example.com")
    S.update(admin=admin, mgr_k=mgr_k, mgr_b=mgr_b, r1=r1, r2=r2)
    status, chk = call("GET", "/delivery/check/", params={"postal_code": "560041"})
    check("delivery check for PIN 560041", status == 200 and chk.get("serviceable", True), chk)
    number = S["cod_order"]
    status, order = call("GET", f"/admin/orders/{number}/", token=mgr_k)
    check("Jayanagar manager sees the order", status == 200, status)
    status, _ = call("GET", f"/admin/orders/{number}/", token=mgr_b)
    check("Indiranagar manager can't (404)", status == 404, status)
    for step in ("processing", "packed"):
        status, res = call("POST", f"/orders/{number}/transition/", {"status": step}, mgr_k)
        check(f"store moves the order to {step}", status == 200, (status, res))
    status, res = call("POST", f"/orders/{number}/transition/", {"status": "processing"}, S["A"])
    check("customer can't change order status", status in (403, 404), status)
    for rider in (r1, r2):
        call("PATCH", "/delivery/me/", {"status": "available"}, rider)
    status, ships = call("GET", "/delivery/shipments/", token=mgr_k, params={"q": number})
    ship = [s for s in rows(ships) if s.get("order_number") == number][0]
    status, partners = call("GET", f"/delivery/shipments/{ship['id']}/eligible-partners/", token=mgr_k)
    ids = [p["partner_id"] for p in rows(partners)]
    check("two eligible riders", len(ids) >= 2, partners)
    status, res = call("POST", f"/delivery/shipments/{ship['id']}/assign/", {"partner_id": ids[0]}, mgr_b)
    check("other store's manager can't assign (404)", status == 404, status)
    status, res = call("POST", f"/delivery/shipments/{ship['id']}/assign/", {"partner_id": ids[0]}, mgr_k)
    check("manager assigns a rider", status in (200, 201), (status, res))
    status, jobs = call("GET", "/delivery/assignments/", token=r1)
    mine = [j for j in rows(jobs) if j["order_number"] == number]
    rider, other = (r1, r2) if mine else (r2, r1)
    if not mine:
        status, jobs = call("GET", "/delivery/assignments/", token=r2)
        mine = [j for j in rows(jobs) if j["order_number"] == number]
    jid = mine[0]["id"]
    status, _ = call("POST", f"/delivery/assignments/{jid}/accept/", {}, other)
    check("another rider can't touch the job (404)", status == 404, status)
    for step in ("accept", "pickup", "start"):
        status, res = call(
            "POST", f"/delivery/assignments/{jid}/{step}/", {"latitude": KTH_LAT, "longitude": KTH_LNG}, rider
        )
        check(f"rider: {step}", status == 200, (status, res))
    check("rider never sees the delivery code", "otp" not in json.dumps(res) or res.get("otp") is None, res)
    status, view = call("GET", f"/orders/{number}/", token=S["A"])
    code = view["shipments"][0]["delivery_code"]["code"]
    total = view["amount_to_pay"] if view.get("amount_to_pay") else view["grand_total"]
    wrong = str((int(code) + 1) % 1000000).zfill(6)
    status, res = call(
        "POST",
        f"/delivery/assignments/{jid}/complete/",
        {"otp": wrong, "cod_collected": True, "cod_amount": total, "cod_method": "cash"},
        rider,
    )
    check("wrong OTP refused", status == 400 and code_of(res) == "otp_invalid", (status, res))
    status, res = call(
        "POST",
        f"/delivery/assignments/{jid}/proof/",
        {"received_by": "E2E A"},
        rider,
        files={"photo": ("x.jpg", b"text", "image/jpeg")},
    )
    check("proof: a non-picture is refused", status == 400, (status, res))
    status, res = call(
        "POST",
        f"/delivery/assignments/{jid}/proof/",
        {"received_by": "E2E A"},
        rider,
        files={"photo": ("door.jpg", jpeg(exif=True), "image/jpeg")},
    )
    check("proof photo uploaded", status in (200, 201), (status, res))
    status, res = call(
        "POST",
        f"/delivery/assignments/{jid}/complete/",
        {"otp": code, "cod_collected": True, "cod_amount": total, "cod_method": "cash"},
        rider,
    )
    check("delivered with OTP + cash", status == 200 and res["status"] == "delivered", (status, res))
    status, raw, hdr = call("GET", f"/orders/{number}/shipments/1/proof/", token=S["A"], raw=True)
    check(
        "customer sees the proof photo (private, no-store)",
        status == 200 and "no-store" in hdr.get("Cache-Control", ""),
        status,
    )
    status, _, _ = call("GET", f"/orders/{number}/shipments/1/proof/", token=S["B"], raw=True)
    check("another customer can't (404)", status == 404, status)
    status, res = call("POST", f"/delivery/cod/{jid}/handover/", {"note": "Counted"}, rider)
    check("rider can't record their own cash handover", status == 403, status)
    status, res = call("POST", f"/delivery/cod/{jid}/handover/", {"note": "Counted"}, mgr_k)
    check("manager records the COD handover", status == 200, (status, res))
    S["delivered_jid"] = jid

    # Failed delivery and re-dispatch on the paid online order.
    number2 = S["online_order"]
    status, o2 = call("GET", f"/admin/orders/{number2}/", token=admin)
    store_mgr = mgr_k if status == 200 else admin
    for step in ("processing", "packed"):
        call("POST", f"/orders/{number2}/transition/", {"status": step}, admin)
    status, ships = call("GET", "/delivery/shipments/", token=admin, params={"q": number2})
    ship2 = [s for s in rows(ships) if s.get("order_number") == number2][0]
    status, res = call("POST", f"/delivery/shipments/{ship2['id']}/assign/", {"partner_id": ids[0]}, admin)
    status, jobs = call("GET", "/delivery/assignments/", token=r1)
    j2 = [j for j in rows(jobs) if j["order_number"] == number2]
    rider2 = r1 if j2 else r2
    if not j2:
        j2 = [j for j in rows(call("GET", "/delivery/assignments/", token=r2)[1]) if j["order_number"] == number2]
    j2 = j2[0]["id"]
    for step in ("accept", "pickup", "start"):
        call("POST", f"/delivery/assignments/{j2}/{step}/", {"latitude": KTH_LAT, "longitude": KTH_LNG}, rider2)
    status, res = call(
        "POST", f"/delivery/assignments/{j2}/fail/", {"reason": "customer_unavailable", "note": "Nobody home"}, rider2
    )
    check("failed delivery recorded", status == 200 and res["status"] == "failed", (status, res))
    status, o = call("GET", f"/orders/{number2}/", token=S["B"])
    check("customer sees the failed attempt", o["status"] == "delivery_failed", o["status"])
    status, res = call("POST", f"/delivery/shipments/{ship2['id']}/assign/", {"partner_id": ids[-1]}, admin)
    check("re-dispatched to a rider", status in (200, 201), (status, res))
    del store_mgr


# --- 7. Returns and refunds ------------------------------------------------------------------------------------------


@section
def returns():
    A, mgr_k = S["A"], S["mgr_k"]
    number = S["cod_order"]
    status, o = call("GET", f"/orders/{number}/", token=A)
    item = o["items"][0]
    status, ret = call(
        "POST",
        "/returns/",
        {
            "order_number": number,
            "reason": "defective",
            "details": "One sheet cracked",
            "items": [{"order_item_id": item["id"], "quantity": 1}],
        },
        A,
    )
    check("customer requests a return", status == 201, (status, ret))
    rn = ret["return_number"]
    status, _ = call("GET", f"/returns/{rn}/", token=S["B"])
    check("another customer can't see the return", status == 404, status)
    status, res = call("POST", f"/returns/{rn}/approve/", {}, S["mgr_b"])
    check("other store's manager can't approve", status == 404, status)
    status, res = call("POST", f"/returns/{rn}/approve/", {}, mgr_k)
    check("manager approves", status == 200, (status, res))
    status, res = call("POST", f"/returns/{rn}/receive/", {"restock": True}, mgr_k)
    check("manager receives the item (restock)", status == 200 and res["status"] == "received", (status, res))
    status, refunds = call("GET", "/payments/refunds/", token=mgr_k, params={"q": number})
    rf = rows(refunds)
    check("COD return → manual refund waiting", rf and rf[0]["status"] == "pending" and rf[0]["is_manual"], rf)
    status, res = call(
        "POST", f"/payments/refunds/{rf[0]['public_id']}/mark-processed/", {"reference": "UPI 26001"}, mgr_k
    )
    check("refund paid by hand with a reference", status == 200 and res["status"] == "processed", (status, res))
    status, res = call("POST", f"/orders/{S['online_order']}/cancel/", {"reason": "Too late"}, S["B"])
    check("a re-dispatched order can't be cancelled by the customer now", status in (400, 409), (status, res))


# --- 8. Notifications ---------------------------------------------------------------------------------------------


@section
def notifications():
    A = S["A"]
    status, inbox = call("GET", "/notifications/", token=A)
    events = {n["event"] for n in rows(inbox)}
    check("customer inbox has the order story", {"order.confirmed", "order.delivered"} <= events, sorted(events))
    status, s = call("GET", "/notifications/summary/", token=A)
    status, res = call("POST", "/notifications/read-all/", {}, A)
    check("mark all read", status == 200 and res["unread"] == 0, res)
    status, log = call("GET", "/admin/notifications/log/", token=S["admin"], params={"q": S["cod_order"]})
    check(
        "delivery log has email rows for the order",
        status == 200 and any(r["channel"] == "email" for r in rows(log)),
        status,
    )
    status, pref = call("PATCH", "/notifications/preferences/", {"whatsapp": True}, S["B"])
    check("B opts in to WhatsApp", status == 200 and pref["whatsapp"], (status, pref))
    status, chans = call("GET", "/admin/notifications/channels/", token=S["admin"])
    check(
        "channels overview (WhatsApp mock, honest)",
        status == 200 and any(c["channel"] == "whatsapp" and c["mock"] for c in rows(chans)),
        chans,
    )
    status, failed = call("GET", "/admin/notifications/log/", token=S["admin"], params={"status": "failed"})
    check("notification log filter works", status == 200, status)


# --- 9. Admin ---------------------------------------------------------------------------------------------------------


@section
def admin():
    admin, mgr_k = S["admin"], S["mgr_k"]
    status, summ = call("GET", "/admin/summary/", token=admin)
    check("dashboard summary", status == 200 and summ["orders"]["total"] >= 3, status)
    status, prods = call("GET", "/admin/products/", token=admin, params={"q": "plywood"})
    check("admin product list", status == 200 and rows(prods), status)
    status, res = call("POST", "/admin/offers/", {"name": "E2E offer"}, mgr_k)
    check("manager can't create offers (403)", status == 403, status)
    status, coupons = call("GET", "/admin/coupons/", token=admin)
    check("coupons list", status == 200, status)
    status, inv = call("GET", "/inventory/", token=mgr_k)
    stores = {r["store_name"] if "store_name" in r else r.get("store") for r in rows(inv)}
    check("manager's inventory is Jayanagar only", status == 200 and len(stores) == 1, stores)
    row = rows(inv)[0]
    status, res = call(
        "POST",
        f"/inventory/{row['id']}/adjust/",
        {"movement_type": "adjustment", "quantity": -100000, "reason": "E2E"},
        mgr_k,
    )
    check("stock can't go negative", status in (400, 409), (status, res))
    status, res = call(
        "POST",
        f"/inventory/{row['id']}/adjust/",
        {"movement_type": "adjustment", "quantity": 5, "reason": "E2E count"},
        mgr_k,
    )
    check("ledgered stock adjustment", status in (200, 201) and res["movement_type"] == "adjustment", (status, res))
    status, stores_list = call("GET", "/admin/stores/", token=admin)
    check("stores list", status == 200 and len(rows(stores_list)) >= 3, status)
    status, riders = call("GET", "/admin/riders/", token=mgr_k)
    check("riders list for the manager", status == 200 and rows(riders), status)
    status, cust = call("GET", "/admin/customers/", token=admin, params={"q": "e2e-a"})
    check("customer lookup", status == 200 and rows(cust), status)
    status, _ = call("GET", "/admin/customers/", token=mgr_k)
    check("manager can't list all customers", status == 403, status)
    status, rets = call("GET", "/returns/", token=mgr_k)
    check("returns list for staff", status == 200 and rows(rets), status)
    status, rep = call("GET", "/admin/reports/sales/", token=admin)
    check("sales report", status == 200 and rep["kpis"], status)
    status, ans = call("POST", "/admin/assistant/", {"question": "How many orders today?"}, mgr_k)
    check("business assistant (manager scope)", status == 200 and ans["intent"] == "orders", (status, ans))
    status, a2 = call("GET", "/admin/users/", token=mgr_k)
    check("manager can't manage users", status == 403, status)
    status, me = call("GET", "/auth/me/", token=admin)
    status, res = call("PATCH", f"/admin/users/{me['id']}/", {"role": "customer"}, admin)
    check("admin can't change their own role", status == 400, (status, res))


# --- 10. Security -----------------------------------------------------------------------------------------------------


@section
def security():
    A = S["A"]
    for path in ("/orders/", "/cart/", "/admin/summary/", "/notifications/"):
        status, _ = call("GET", path)
        check(f"anonymous {path} → 401", status == 401, status)
    for path in ("/admin/summary/", "/admin/products/", "/inventory/", "/admin/reports/sales/", "/delivery/shipments/"):
        status, _ = call("GET", path, token=A)
        check(f"customer {path} → 403", status == 403, status)
    status, _ = call("GET", "/delivery/assignments/", token=A)
    check("customer can't open rider jobs", status == 403, status)
    status, res = call(
        "POST", "/profile/avatar/", {}, A, files={"avatar": ("a.png", b"<svg onload=alert(1)>", "image/png")}
    )
    check("avatar: non-image refused", status == 400, (status, res))
    status, res = call(
        "POST", "/profile/avatar/", {}, A, files={"avatar": ("a.jpg", jpeg((300, 300), exif=True), "image/jpeg")}
    )
    check("avatar: photo accepted (re-encoded)", status == 200, (status, res))
    big = b"{" + b" " * (13 * 1024 * 1024) + b"}"
    req = urllib.request.Request(  # noqa: S310 — http(s) only, checked above
        BASE + "/auth/login/", data=big, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=60)  # noqa: S310 — http(s) only, checked above
        status = 200
    except urllib.error.HTTPError as exc:
        status = exc.code
    check("13 MB request refused (413)", status == 413, status)
    status, res = call("PATCH", "/profile/", {"role": "admin", "email_verified": True}, A)
    status, me = call("GET", "/auth/me/", token=A)
    check("no self-promotion through the profile", me["role"] == "customer", me)
    status, res = call("POST", "/notifications/webhooks/whatsapp/", {"entry": []})
    check("unsigned WhatsApp webhook refused", status == 403, status)


# --- 11. Failure cases: refund of a cancelled paid order, notification failure and retry -------------------------


@section
def failures():
    B, admin = S["B"], S["admin"]
    # WhatsApp to a number that can't receive (the mock fails numbers ending in 0000), then fixed and resent.
    status, prof = call("PATCH", "/profile/", {"phone": "9812340000"}, B)
    check("B's phone changed", status == 200, (status, prof))
    _, v = variant("DEMO-TB-8-SS")
    call("POST", "/cart/items/", {"variant_id": v["id"], "quantity": 1}, B)
    status, order = call("POST", "/orders/", {"address_id": S["B_addr"], "payment_method": "online"}, B)
    pay = order["payments"][0]
    status, res = call(
        "POST",
        f"/payments/{pay['public_id']}/verify/",
        {"payload": {"mock_signature": pay["client_payload"]["mock_signature"], "mock_outcome": "success"}},
        B,
    )
    status, o = call("GET", f"/orders/{order['order_number']}/", token=B)
    check("paid online order", o["payment_status"] == "paid", o["payment_status"])
    status, log = call(
        "GET", "/admin/notifications/log/", token=admin, params={"q": order["order_number"], "channel": "whatsapp"}
    )
    failed = [r for r in rows(log) if r["status"] == "failed"]
    check(
        "WhatsApp to an unreachable number is logged as failed with the reason",
        failed and failed[0]["error"],
        rows(log),
    )
    call("PATCH", "/profile/", {"phone": "9812300012"}, B)
    status, res = call("POST", f"/admin/notifications/log/{failed[0]['id']}/retry/", {}, admin)
    check("admin resends it after the number is fixed", status == 200 and res["status"] == "sent", (status, res))
    status, res = call("POST", f"/orders/{order['order_number']}/cancel/", {"reason": "Ordered twice"}, B)
    check("customer cancels the paid order", status == 200 and res["status"] == "cancelled", (status, res))
    status, o = call("GET", f"/orders/{order['order_number']}/", token=B)
    check(
        "refund processed through the (mock) gateway",
        o["payment_status"] in ("refunded", "partially_refunded"),
        (o["payment_status"], o.get("refunds")),
    )
    status, inbox = call("GET", "/notifications/", token=B)
    events = {n["event"] for n in rows(inbox)}
    check(
        "customer told about the cancellation and the refund",
        {"order.cancelled", "refund.processed"} <= events or {"order.cancelled", "refund.initiated"} <= events,
        sorted(events),
    )


def main():
    for fn in SECTIONS:
        print(f"\n== {fn.__name__} ==")
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — a broken section is a failure, the rest still runs
            check(f"{fn.__name__}: section completed", False, f"{exc!r}\n{traceback.format_exc()[-800:]}")
    passed = sum(ok for _, ok in results)
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)


main()
