# ruff: noqa: E501 — explanations read better on one line
"""CompatibilityService (Phase 21): will product A work with product B? Which accessories go with a product?

Order of evidence, strongest first:
1. the shop's own links (`ProductRelation`, managed by staff, audited): "incompatible" → NOT_COMPATIBLE;
   "compatible"/"required" → COMPATIBLE unless the listings' facts contradict it (then POSSIBLY, both reasons);
2. a deterministic rule for the two kinds of product (`rules.py`) over listing facts (`profiles.py`);
3. an "accessory" link without a rule → POSSIBLY_COMPATIBLE ("the shop lists it as going with it");
4. nothing → INSUFFICIENT_INFORMATION ("Not enough information to confirm compatibility.").

Read-only. The AI layer may phrase the explanation (apps.ai.services.compatibility) but never changes a verdict.
"""

from dataclasses import dataclass, field

from django.db.models import Q

from apps.core.exceptions import NotFoundError, ServiceError

from .. import selectors
from ..models import Product, ProductRelation, ProductVariant
from . import profiles, rules
from .rules import COMPATIBLE, NOT, ORDER, POSSIBLY, UNKNOWN, Check, Finding

NO_INFO = "Not enough information to confirm compatibility."
RECOMMEND_LIMIT = 8
CANDIDATES_PER_KIND = 40


class CompatibilityError(ServiceError):
    default_code = "compatibility_error"


@dataclass
class Result:
    verdict: str
    reason: str
    product_a: object
    product_b: object
    variant_a: object | None = None
    variant_b: object | None = None
    checks: list[Check] = field(default_factory=list)
    matching_variants: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # relation:<kind> | rule:<a>+<b> | none
    kinds: tuple = (None, None)

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "product_a": {"id": self.product_a.pk, "name": self.product_a.name, "slug": self.product_a.slug, "kind": self.kinds[0]},
            "product_b": {"id": self.product_b.pk, "name": self.product_b.name, "slug": self.product_b.slug, "kind": self.kinds[1]},
            "variant_a": self.variant_a.pk if self.variant_a else None,
            "variant_b": self.variant_b.pk if self.variant_b else None,
            "checks": [{"name": c.name, "status": c.status, "detail": c.detail} for c in self.checks],
            "matching_variants": self.matching_variants,
            "sources": self.sources,
        }  # fmt: skip


def _products():
    return Product.objects.filter(is_active=True, is_published=True, is_deleted=False).select_related("category", "subcategory").prefetch_related(
        "specifications", "variants__option_values__option_type", "variants__option_values__value"
    )  # fmt: skip


class CompatibilityService:
    # --- Loading -------------------------------------------------------------------------------------------

    @staticmethod
    def load(product_id: int, variant_id: int | None = None):
        product = _products().filter(pk=product_id).first()
        if product is None:
            raise NotFoundError("Product not found.")
        variant = None
        if variant_id:
            variant = next((v for v in product.variants.all() if v.pk == variant_id and v.is_active), None)
            if variant is None:
                raise CompatibilityError("Choose one of this product's variants.", code="invalid_variant")
        return product, variant

    @staticmethod
    def load_many(product_ids) -> dict:
        """Published products with everything a check reads, in one go (one product checked against many)."""
        return {p.pk: p for p in _products().filter(pk__in=list(product_ids))}

    @staticmethod
    def links_between(product_id: int, other_ids) -> dict:
        """The shop's links between one product and several others, keyed (product_id, related_id), for `check`."""
        other_ids = list(other_ids)
        rows = ProductRelation.objects.filter(
            Q(product_id=product_id, related_id__in=other_ids) | Q(product_id__in=other_ids, related_id=product_id)
        )
        return {(r.product_id, r.related_id): r for r in rows}

    # --- One pair ------------------------------------------------------------------------------------------

    def check_ids(
        self, product_a: int, product_b: int, variant_a: int | None = None, variant_b: int | None = None
    ) -> Result:
        if product_a == product_b:
            raise CompatibilityError("Choose two different products.", code="same_product")
        a, va = self.load(product_a, variant_a)
        b, vb = self.load(product_b, variant_b)
        return self.check(a, b, va, vb)

    def check(self, a, b, variant_a=None, variant_b=None, relations: dict | None = None) -> Result:
        """`relations` (from `links_between`) saves the link query when one product is checked against many."""
        pa, pb = profiles.build(a, variant_a), profiles.build(b, variant_b)
        if relations is None:
            relations = {
                (r.product_id, r.related_id): r
                for r in ProductRelation.objects.filter(Q(product=a, related=b) | Q(product=b, related=a))
            }
        link = relations.get((a.pk, b.pk)) or relations.get((b.pk, a.pk))
        found = self._rule_finding(pa, pb)
        result = Result(UNKNOWN, NO_INFO, a, b, variant_a, variant_b, kinds=(pa.kind, pb.kind))
        if found is not None:
            finding, rule_name = found
            result.verdict, result.reason, result.checks = finding.verdict, finding.reason, finding.checks
            result.matching_variants = finding.matching_variants
            result.sources.append(f"rule:{rule_name}")
        if link is not None:
            result.sources.insert(0, f"relation:{link.kind}")
            note = f" ({link.note})" if link.note else ""
            if link.kind == ProductRelation.Kind.INCOMPATIBLE:
                result.verdict = NOT
                result.reason = f"The shop has marked these as not working together{note}. " + (
                    result.reason if found and result.verdict != COMPATIBLE else ""
                )
                result.checks.insert(0, Check("shop", "fail", f"Marked incompatible by the shop{note}."))
            elif link.kind in (ProductRelation.Kind.COMPATIBLE, ProductRelation.Kind.REQUIRED):
                verified = "needed with" if link.kind == ProductRelation.Kind.REQUIRED else "compatible with"
                result.checks.insert(
                    0, Check("shop", "pass", f"The shop lists it as {verified} the other product{note}.")
                )
                if found is None or result.verdict in (COMPATIBLE, UNKNOWN):
                    result.verdict = COMPATIBLE
                    result.reason = f"The shop has confirmed these work together{note}." + (
                        f" {found[0].reason}" if found and found[0].verdict == COMPATIBLE else ""
                    )
                else:  # the listings disagree with the link: never claim more than the facts allow
                    result.verdict = POSSIBLY
                    result.reason = f"The shop lists these together{note}, but the listings say: {result.reason}"
            elif found is None or result.verdict == UNKNOWN:
                result.verdict = POSSIBLY
                result.reason = (
                    f"The shop lists it as going with this product{note}, but the specifications don't confirm the fit."
                )
        result.reason = result.reason.strip()
        return result

    @staticmethod
    def _rule_finding(pa, pb) -> tuple[Finding, str] | None:
        fn, swapped = rules.find_rule(pa.kind, pb.kind)
        if fn is None:
            return None
        finding = fn(pb, pa) if swapped else fn(pa, pb)
        if swapped:  # matching pairs are always returned as {a: product A's variant, b: product B's}
            finding.matching_variants = [
                {"a": m["b"], "b": m["a"], "label": m["label"]} for m in finding.matching_variants
            ]
        name = f"{pb.kind}+{pa.kind}" if swapped else f"{pa.kind}+{pb.kind}"
        return finding, name

    # --- Accessories ---------------------------------------------------------------------------------------

    def accessories(self, product_id: int, variant_id: int | None = None) -> dict:
        """Groups for the product page: required, compatible (shop links + products the rules confirm),
        commonly used (shop's accessory links), alternatives. Only published products; never an incompatible one."""
        product, variant = self.load(product_id, variant_id)
        links = list(product.relations.select_related("related").order_by("sort_order", "id"))
        live = set(
            selectors.product_queryset().filter(pk__in=[r.related_id for r in links]).values_list("pk", flat=True)
        )
        incompatible = {r.related_id for r in links if r.kind == ProductRelation.Kind.INCOMPATIBLE}
        incompatible |= set(
            ProductRelation.objects.filter(related=product, kind=ProductRelation.Kind.INCOMPATIBLE).values_list(
                "product_id", flat=True
            )
        )
        groups = {"required": [], "compatible": [], "accessories": [], "alternatives": []}
        kind_group = {
            "required": "required",
            "compatible": "compatible",
            "accessory": "accessories",
            "alternative": "alternatives",
        }
        seen = {product.pk}
        for link in links:
            if link.related_id not in live or link.kind not in kind_group or link.related_id in seen:
                continue
            seen.add(link.related_id)
            groups[kind_group[link.kind]].append(
                {
                    "product_id": link.related_id,
                    "note": link.note,
                    "source": "shop",
                    "verdict": None,
                    "reason": link.note,
                }
            )
        # products the rules confirm (published, in categories the rules pair this kind with)
        profile = profiles.build(product, variant)
        candidates = self._candidates(profile.kind, exclude=seen | incompatible)
        relations = self.links_between(product.pk, [c.pk for c in candidates])  # one query for all candidates
        for candidate in candidates:
            result = self.check(product, candidate, variant, None, relations=relations)
            if result.verdict in (COMPATIBLE, POSSIBLY) and len(groups["compatible"]) < RECOMMEND_LIMIT:
                seen.add(candidate.pk)
                groups["compatible"].append({"product_id": candidate.pk, "note": "", "source": "rules", "verdict": result.verdict, "reason": result.reason,
                                             "variant_id": next((m["b"] for m in result.matching_variants if m["a"] in (None, getattr(variant, "pk", None))), None)})  # fmt: skip
        groups["compatible"].sort(key=lambda row: (row["source"] != "shop", ORDER.get(row["verdict"] or COMPATIBLE, 0)))
        return {"product_id": product.pk, "kind": profile.kind, "groups": groups}

    def _candidates(self, kind: str | None, *, exclude: set[int]) -> list:
        if kind is None:
            return []
        wanted = set(rules.related_kinds(kind))
        if not wanted:
            return []
        # loaded once per service instance and kind: a kit with several problems doesn't reload the catalogue
        pool = self.__dict__.setdefault("_candidate_pool", {})
        if kind not in pool:
            pool[kind] = [c for c in _products().order_by("name")[:500] if profiles.kind_of(c) in wanted]
        rows = [c for c in pool[kind] if c.pk not in exclude]
        return rows[: CANDIDATES_PER_KIND * len(wanted)]

    def compatible_options(
        self, anchor, anchor_variant, replace_kind: str | None, *, exclude: set[int] = frozenset(), limit: int = 4
    ) -> list[dict]:
        """Products of `replace_kind` that work with `anchor` ("View compatible options"), best first."""
        out = []
        candidates = [
            c
            for c in self._candidates(profiles.kind_of(anchor), exclude={anchor.pk, *exclude})
            if not replace_kind or profiles.kind_of(c) == replace_kind
        ]
        relations = self.links_between(anchor.pk, [c.pk for c in candidates])  # one query for all candidates
        for candidate in candidates:
            result = self.check(anchor, candidate, anchor_variant, None, relations=relations)
            if result.verdict == COMPATIBLE or (result.verdict == POSSIBLY and result.matching_variants):
                variant_id = next(
                    (m["b"] for m in result.matching_variants if m["a"] in (None, getattr(anchor_variant, "pk", None))),
                    None,
                )
                out.append(
                    {
                        "product_id": candidate.pk,
                        "variant_id": variant_id,
                        "verdict": result.verdict,
                        "reason": result.reason,
                    }
                )
        out.sort(key=lambda row: ORDER[row["verdict"]])
        return out[:limit]

    # --- A set of lines (project kits, Quantity AI, the cart) ----------------------------------------------

    def check_lines(self, lines: list[dict]) -> list[dict]:
        """lines: [{key, variant}] (variant = ProductVariant with product). Every pair with a rule or a shop link
        is checked; problems come back with compatible replacements for the second line."""
        if len(lines) < 2:
            return []
        product_ids = {line["variant"].product_id for line in lines if line.get("variant") is not None}
        products = {p.pk: p for p in _products().filter(pk__in=product_ids)}
        variants = {
            v.pk: v
            for v in ProductVariant.objects.filter(
                pk__in=[line["variant"].pk for line in lines if line.get("variant")]
            ).prefetch_related("option_values__option_type", "option_values__value")
        }
        # every link between the lines, loaded once for all pairs
        links = {
            (r.product_id, r.related_id): r
            for r in ProductRelation.objects.filter(product_id__in=product_ids, related_id__in=product_ids)
        }
        # without a rule, only an "incompatible" link is worth a warning ("goes with" isn't a fit claim)
        marked = {key for key, r in links.items() if r.kind == ProductRelation.Kind.INCOMPATIBLE}
        out = []
        usable = [line for line in lines if line.get("variant") is not None and line["variant"].product_id in products]
        for i, first in enumerate(usable):
            for second in usable[i + 1 :]:
                a, b = products[first["variant"].product_id], products[second["variant"].product_id]
                if a.pk == b.pk:
                    continue
                kind_a, kind_b = profiles.kind_of(a), profiles.kind_of(b)
                has_rule = rules.find_rule(kind_a, kind_b)[0] is not None
                if not has_rule and (a.pk, b.pk) not in marked and (b.pk, a.pk) not in marked:
                    continue
                result = self.check(
                    a, b, variants.get(first["variant"].pk), variants.get(second["variant"].pk), relations=links
                )
                if result.verdict == COMPATIBLE:
                    continue
                out.append({
                    "keys": [first["key"], second["key"]],
                    **result.as_dict(),
                    "message": _problem_message(result),
                    "options": self.compatible_options(a, variants.get(first["variant"].pk), kind_b, exclude={b.pk}),
                })  # fmt: skip
        return out


def _problem_message(result: Result) -> str:
    b = result.product_b.name
    a = result.product_a.name
    if result.verdict == NOT:
        return f"Your selected {b} won't work with {a}. {result.reason}"
    if result.verdict == POSSIBLY:
        return f"Your selected {b} may not work with {a}. {result.reason}"
    return f"We can't confirm that {b} works with {a}. {result.reason}"
