"""What a delivery partner does with a job (Phase 10).

    Delivery:       assigned ─accept→ accepted ─pickup→ picked_up ─start→ out_for_delivery ─complete→ delivered
    Return pickup:  assigned ─accept→ accepted ─pickup (from customer)→ picked_up ─complete (at store)→ delivered
    Either:         assigned/accepted ─reject→ rejected        picked_up/out_for_delivery ─fail→ failed
                    (a return pickup can also fail before pickup: nobody at home)

Rules enforced here, never in the client:
- A rider acts only on their own assignments; anything else is "not found".
- Each step is valid from exactly one status; everything else is `invalid_delivery_state`.
- Pickup needs a packed order. It turns the shipment's reservation into a sale.
- Completing a delivery needs the customer's OTP (apps.delivery.otp), the cash for a COD order,
  and a photo when DELIVERY_PROOF_REQUIRED. Staff can close a delivery without the OTP; that is
  flagged on the assignment and audit-logged.
- The order follows its shipments (orders.shipments.sync_order_status). Prices, items and
  customer data are never writable from here.

Locks: order → assignment → partner, in that order, everywhere (also apps.delivery.assignment),
so two people acting on the same job wait for each other instead of deadlocking.
"""

import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError, NotFoundError, ServiceError
from apps.core.money import q
from apps.notifications.services import notify_order, notify_order_staff
from apps.orders.models import Order, OrderShipment, OrderStatus, PaymentMethod, ReturnRequest, ShipmentStatus
from apps.orders.shipments import sell_stock, sync_order_status

from . import otp
from .assignment import record_history, refresh_partner_status
from .models import DeliveryAssignment, DeliveryPartner
from .proof import clean_photo

logger = logging.getLogger(__name__)
A = DeliveryAssignment.Status
KIND = DeliveryAssignment.Kind
# The store has packed the order (other shipments of it may already be further along, or failed).
PACKED_FOR_PICKUP = (
    OrderStatus.PACKED,
    OrderStatus.ASSIGNED,
    OrderStatus.PICKED_UP,
    OrderStatus.OUT_FOR_DELIVERY,
    OrderStatus.DELIVERY_FAILED,
)


class DeliveryStateError(ConflictError):
    default_code = "invalid_delivery_state"


class DeliveryError(ServiceError):
    default_code = "delivery_error"


def earning_for(assignment: DeliveryAssignment) -> Decimal:
    distance = assignment.distance_km or Decimal("0")
    return q(settings.DELIVERY_EARNING_BASE + settings.DELIVERY_EARNING_PER_KM * distance)


# --- Locking and checks --------------------------------------------------------------------------


def _lock(assignment_id: int, *, rider=None) -> tuple[Order, DeliveryAssignment]:
    """Lock order → assignment. With `rider` (a user), the job must be theirs."""
    found = DeliveryAssignment.objects.filter(pk=assignment_id).values("order_id", "partner__user_id").first()
    if found is None or (rider is not None and found["partner__user_id"] != rider.pk):
        raise NotFoundError("Delivery job not found.")
    order = Order.objects.select_for_update().get(pk=found["order_id"])
    assignment = (
        DeliveryAssignment.objects.select_for_update()
        .select_related("partner__user", "shipment__store", "return_request")
        .get(pk=assignment_id)
    )
    assignment.order = order
    return order, assignment


def _require(assignment: DeliveryAssignment, *allowed: str, action: str) -> None:
    if assignment.status not in allowed:
        raise DeliveryStateError(
            f"This job is {assignment.get_status_display().lower()} and can't be {action}.",
            details={"status": assignment.status},
        )


def _require_partner_active(assignment: DeliveryAssignment) -> None:
    partner = assignment.partner
    if not (partner.is_active and partner.is_verified and partner.user.is_active):
        raise ConflictError("Your delivery partner account is not active.", code="partner_inactive")


def _move(assignment: DeliveryAssignment, status: str, *, actor, note: str = "", position=None, fields=()) -> None:
    previous = assignment.status
    assignment.status = status
    assignment.save(update_fields=["status", "updated_at", *fields])
    latitude, longitude = position or (None, None)
    record_history(assignment, previous, actor=actor, note=note, latitude=latitude, longitude=longitude)


def _free(assignment: DeliveryAssignment) -> None:
    refresh_partner_status(DeliveryPartner.objects.select_for_update().get(pk=assignment.partner_id))


def _shipment(assignment: DeliveryAssignment) -> OrderShipment:
    return OrderShipment.objects.select_related("store").prefetch_related("items").get(pk=assignment.shipment_id)


def _rider_name(assignment: DeliveryAssignment) -> str:
    return assignment.partner.user.full_name.split(" ")[0] or "Your delivery partner"


def _tell_customer(order: Order, event: str, assignment: DeliveryAssignment, shipment, **context) -> None:
    """One message per delivery attempt (the assignment), so a second attempt is told again."""
    data = {"shipment": shipment.sequence, "assignment_id": assignment.pk}
    notify_order(order, event, data=data, **context)


def tell_delivery_code(order: Order, assignment: DeliveryAssignment) -> None:
    """The delivery code by WhatsApp/SMS for customers who opted in (it is also on the order page).
    The code itself is never stored with the message: it is looked up again when sending."""
    notify_order(order, "delivery.otp", key=f"otp:{assignment.pk}:{assignment.otp_nonce[:12]}",
                 data={"assignment_id": assignment.pk}, otp="")  # fmt: skip


# --- Steps ---------------------------------------------------------------------------------------


@transaction.atomic
def accept(assignment_id: int, *, rider) -> DeliveryAssignment:
    _order, assignment = _lock(assignment_id, rider=rider)
    _require(assignment, A.ASSIGNED, action="accepted")
    _require_partner_active(assignment)
    assignment.accepted_at = timezone.now()
    _move(assignment, A.ACCEPTED, actor=rider, note="Accepted by the delivery partner", fields=["accepted_at"])
    return assignment


@transaction.atomic
def reject(assignment_id: int, *, rider, reason: str) -> DeliveryAssignment:
    """The rider can't take the job. It goes back to the store's waiting list."""
    if not reason.strip():
        raise DeliveryError("Tell the store why you can't take this job.", code="reason_required")
    order, assignment = _lock(assignment_id, rider=rider)
    _require(assignment, *DeliveryAssignment.BEFORE_PICKUP, action="rejected")
    assignment.rejected_at, assignment.reject_reason = timezone.now(), reason.strip()[:255]
    _move(assignment, A.REJECTED, actor=rider, note=assignment.reject_reason, fields=["rejected_at", "reject_reason"])
    _free(assignment)
    if assignment.kind == KIND.DELIVERY:
        shipment = _shipment(assignment)
        if shipment.status == ShipmentStatus.ASSIGNED:
            shipment.status = ShipmentStatus.PENDING
            shipment.save(update_fields=["status"])
        sync_order_status(order, actor=rider, note="Delivery partner rejected the job")
    record_audit(
        action="delivery.reject",
        actor=rider,
        target=assignment,
        changes={"order": order.order_number, "reason": assignment.reject_reason},
    )
    return assignment


@transaction.atomic
def pickup(assignment_id: int, *, rider, position=None) -> DeliveryAssignment:
    """Delivery: the rider takes the packed goods at the store. Return: from the customer."""
    order, assignment = _lock(assignment_id, rider=rider)
    _require(assignment, A.ACCEPTED, action="picked up")
    _require_partner_active(assignment)
    now = timezone.now()
    if assignment.kind == KIND.RETURN_PICKUP:
        if assignment.return_request.status != ReturnRequest.Status.APPROVED:
            raise DeliveryStateError("This return is no longer waiting for pickup.", code="return_not_open")
        note = "Return collected from the customer"
    else:
        if order.status not in PACKED_FOR_PICKUP:
            raise DeliveryStateError(
                "The store hasn't finished packing this order yet.",
                code="order_not_packed",
                details={"order_status": order.status},
            )
        shipment = _shipment(assignment)
        sell_stock(shipment, actor=rider)
        shipment.status, shipment.picked_up_at = ShipmentStatus.PICKED_UP, now
        shipment.save(update_fields=["status", "picked_up_at"])
        note = "Picked up at the store"
    assignment.picked_up_at = now
    _move(assignment, A.PICKED_UP, actor=rider, note=note, position=position, fields=["picked_up_at"])
    if assignment.kind == KIND.DELIVERY:
        sync_order_status(order, actor=rider, note="Picked up by the delivery partner")
        _tell_customer(order, "order.picked_up", assignment, shipment, rider_name=_rider_name(assignment),
                       store_name=shipment.store.name)  # fmt: skip
    return assignment


@transaction.atomic
def start_delivery(assignment_id: int, *, rider, position=None) -> DeliveryAssignment:
    """The rider leaves for the customer. The delivery code is issued now."""
    order, assignment = _lock(assignment_id, rider=rider)
    if assignment.kind != KIND.DELIVERY:
        raise DeliveryStateError("Return pickups go straight to the store.", code="not_a_delivery")
    _require(assignment, A.PICKED_UP, action="started")
    now = timezone.now()
    assignment.out_for_delivery_at = now
    _move(assignment, A.OUT_FOR_DELIVERY, actor=rider, note="Out for delivery", position=position,
          fields=["out_for_delivery_at"])  # fmt: skip
    otp.issue(assignment, now=now)
    shipment = _shipment(assignment)
    shipment.status, shipment.out_for_delivery_at = ShipmentStatus.OUT_FOR_DELIVERY, now
    shipment.delivery_attempts += 1
    shipment.save(update_fields=["status", "out_for_delivery_at", "delivery_attempts"])
    sync_order_status(order, actor=rider, note="Out for delivery")
    _tell_customer(order, "order.out_for_delivery", assignment, shipment, rider_name=_rider_name(assignment))
    tell_delivery_code(order, assignment)
    return assignment


def _collect_cod(assignment: DeliveryAssignment, order: Order, cod: dict | None, now) -> None:
    """Record what the rider collected. The amount must be exactly what the order says."""
    due = assignment.cod_amount_due
    if order.payment_method != PaymentMethod.COD or due <= 0:
        return
    cod = cod or {}
    if not cod.get("collected"):
        raise DeliveryError(
            f"Collect ₹{due} from the customer before completing this delivery.",
            code="cod_not_collected",
            details={"amount_due": str(due)},
        )
    amount = cod.get("amount")
    if amount is None or q(Decimal(str(amount))) != due:
        raise DeliveryError(
            f"The amount to collect is ₹{due}.", code="cod_amount_mismatch", details={"amount_due": str(due)}
        )
    method = cod.get("method") or DeliveryAssignment.CodMethod.CASH
    if method not in DeliveryAssignment.CodMethod.values:
        raise DeliveryError("Choose cash or UPI.", code="cod_method_invalid")
    assignment.cod_collected_amount, assignment.cod_method = due, method
    assignment.cod_reference = str(cod.get("reference") or "")[:60]
    assignment.cod_collected_at = now
    if method == DeliveryAssignment.CodMethod.UPI:
        # Paid straight into the store's account: there is no cash to hand over.
        assignment.cod_handed_over_at = now
        assignment.cod_handover_note = "Paid by UPI to the store"


COMPLETION_FIELDS = [
    "delivered_at",
    "earning_amount",
    "received_by",
    "delivery_notes",
    "otp_attempts",
    "otp_verified_at",
    "completed_without_otp",
    "cod_collected_amount",
    "cod_method",
    "cod_reference",
    "cod_collected_at",
    "cod_handed_over_at",
    "cod_handover_note",
]


def _finish_delivery(order, assignment, *, actor, now, note, position=None) -> None:
    assignment.delivered_at = now
    assignment.earning_amount = earning_for(assignment)
    _move(assignment, A.DELIVERED, actor=actor, note=note, position=position, fields=COMPLETION_FIELDS)
    _free(assignment)
    shipment = _shipment(assignment)
    shipment.status, shipment.delivered_at = ShipmentStatus.DELIVERED, now
    shipment.save(update_fields=["status", "delivered_at"])
    sync_order_status(order, actor=actor, note="Delivered")
    order.refresh_from_db(fields=["status"])
    whole = order.status == OrderStatus.DELIVERED
    if whole:
        notify_order(order, "order.delivered")  # once per order, however many shipments it had
    else:
        _tell_customer(order, "order.part_delivered", assignment, shipment, store_name=shipment.store.name)


def complete_delivery(
    assignment_id: int,
    *,
    rider,
    code: str = "",
    cod: dict | None = None,
    received_by: str = "",
    notes: str | None = None,
    position=None,
) -> DeliveryAssignment:
    """Hand over at the door (delivery) or at the store (return pickup).

    A wrong delivery code is counted even though the request fails, so the counting is
    committed first and the error is raised afterwards.
    """
    refused: tuple[str, str] | None = None
    with transaction.atomic():
        order, assignment = _lock(assignment_id, rider=rider)
        now = timezone.now()
        if notes is not None:
            assignment.delivery_notes = notes.strip()[:500]
        assignment.received_by = received_by.strip()[:120] or assignment.received_by

        if assignment.kind == KIND.RETURN_PICKUP:
            _require(assignment, A.PICKED_UP, action="completed")
            assignment.delivered_at = now
            assignment.earning_amount = earning_for(assignment)
            _move(assignment, A.DELIVERED, actor=rider, note="Return handed over at the store", position=position,
                  fields=["delivered_at", "earning_amount", "received_by", "delivery_notes"])  # fmt: skip
            _free(assignment)
            return assignment

        _require(assignment, A.OUT_FOR_DELIVERY, action="completed")
        if settings.DELIVERY_PROOF_REQUIRED and not assignment.proof_image:
            raise DeliveryError("Upload a photo of the delivery first.", code="proof_required")
        ok, error_code, message = otp.check(assignment, code, now=now)
        if not ok:
            assignment.save(update_fields=["otp_attempts", "updated_at"])
            refused = (error_code, message)
        else:
            _collect_cod(assignment, order, cod, now)
            assignment.otp_verified_at = now
            _finish_delivery(order, assignment, actor=rider, now=now, note="Delivered (code verified)",
                             position=position)  # fmt: skip
    if refused:
        raise otp.OtpError(refused[1], code=refused[0])
    return assignment


@transaction.atomic
def complete_without_otp(assignment_id: int, *, actor, note: str, cod: dict | None = None) -> DeliveryAssignment:
    """Store staff close a delivery whose customer could not show the code (no phone, no signal).
    Flagged on the assignment and audit-logged."""
    if not note.strip():
        raise DeliveryError("Say why the delivery is closed without the customer's code.", code="note_required")
    order, assignment = _lock(assignment_id)
    if assignment.kind != KIND.DELIVERY:
        raise DeliveryStateError("Returns are closed by receiving them at the store.", code="not_a_delivery")
    _require(assignment, A.OUT_FOR_DELIVERY, action="completed")
    now = timezone.now()
    _collect_cod(assignment, order, cod, now)
    assignment.completed_without_otp = True
    _finish_delivery(order, assignment, actor=actor, now=now, note=f"Closed by the store without code: {note}"[:255])
    record_audit(
        action="delivery.complete_without_otp",
        actor=actor,
        target=assignment,
        changes={"order": order.order_number, "partner": assignment.partner_id, "note": note},
    )
    return assignment


@transaction.atomic
def fail_delivery(assignment_id: int, *, rider, reason_code: str, note: str = "", position=None) -> DeliveryAssignment:
    """The delivery (or return pickup) could not be completed. Goods go back to the store."""
    if reason_code not in DeliveryAssignment.FailureCode.values:
        raise DeliveryError("Choose a reason.", code="reason_required")
    if reason_code == DeliveryAssignment.FailureCode.OTHER and not note.strip():
        raise DeliveryError("Describe what happened.", code="note_required")
    order, assignment = _lock(assignment_id, rider=rider)
    allowed = (
        DeliveryAssignment.WITH_GOODS
        if assignment.kind == KIND.DELIVERY
        else (A.ACCEPTED, *DeliveryAssignment.WITH_GOODS)
    )
    _require(assignment, *allowed, action="reported as failed")
    now = timezone.now()
    label = DeliveryAssignment.FailureCode(reason_code).label
    assignment.failed_at, assignment.failure_code = now, reason_code
    assignment.failure_reason = (f"{label}: {note.strip()}" if note.strip() else label)[:255]
    assignment.earning_amount = q(settings.DELIVERY_EARNING_FAILED_ATTEMPT)
    assignment.otp_nonce = assignment.otp_hash = ""  # the code dies with the attempt
    changed = ["failed_at", "failure_code", "failure_reason", "earning_amount", "otp_nonce", "otp_hash"]
    _move(assignment, A.FAILED, actor=rider, note=assignment.failure_reason, position=position, fields=changed)
    _free(assignment)
    if assignment.kind == KIND.DELIVERY:
        shipment = _shipment(assignment)
        shipment.status, shipment.failed_at = ShipmentStatus.FAILED, now
        shipment.failure_reason, shipment.failure_note = reason_code, note.strip()[:255]
        shipment.save(update_fields=["status", "failed_at", "failure_reason", "failure_note"])
        sync_order_status(order, actor=rider, note=f"Delivery attempt failed: {label}")
        _tell_customer(order, "delivery.failed", assignment, shipment, reason=label.lower())
        notify_order_staff(order, "staff.delivery_failed", data={"assignment_id": assignment.pk},
                           store_name=shipment.store.name, reason=assignment.failure_reason)  # fmt: skip
    record_audit(
        action="delivery.fail",
        actor=rider,
        target=assignment,
        changes={"order": order.order_number, "code": reason_code, "note": note},
    )
    return assignment


@transaction.atomic
def update_notes(assignment_id: int, *, rider, notes: str) -> DeliveryAssignment:
    _order, assignment = _lock(assignment_id, rider=rider)
    _require(assignment, *DeliveryAssignment.ACTIVE_STATUSES, action="edited")
    assignment.delivery_notes = notes.strip()[:500]
    assignment.save(update_fields=["delivery_notes", "updated_at"])
    return assignment


def _discard(storage, name: str) -> None:
    try:
        storage.delete(name)
    except OSError:
        logger.warning("Could not delete replaced proof photo %s", name)


@transaction.atomic
def upload_proof(assignment_id: int, *, rider, photo, received_by: str = "") -> DeliveryAssignment:
    """Photo taken at the door (delivery) or of the collected items (return pickup)."""
    _order, assignment = _lock(assignment_id, rider=rider)
    allowed = (A.OUT_FOR_DELIVERY,) if assignment.kind == KIND.DELIVERY else DeliveryAssignment.WITH_GOODS
    _require(assignment, *allowed, action="given a photo")
    cleaned = clean_photo(photo)
    replaced = assignment.proof_image.name if assignment.proof_image else ""
    assignment.proof_image.save(cleaned.name, cleaned, save=False)
    if replaced:
        storage = assignment.proof_image.storage
        # After commit, so a rolled-back upload keeps the earlier photo. A file that is still
        # being read (Windows locks it) is left behind rather than failing the upload.
        transaction.on_commit(lambda: _discard(storage, replaced))
    assignment.proof_uploaded_at = timezone.now()
    if received_by.strip():
        assignment.received_by = received_by.strip()[:120]
    assignment.save(update_fields=["proof_image", "proof_uploaded_at", "received_by", "updated_at"])
    return assignment


@transaction.atomic
def new_delivery_code(order: Order, shipment_sequence: int, *, user) -> DeliveryAssignment:
    """The customer asks for a fresh delivery code (expired, locked, or just to be safe)."""
    order = Order.objects.select_for_update().filter(pk=order.pk, user=user).first()
    if order is None:
        raise NotFoundError("Order not found.")
    assignment = (
        DeliveryAssignment.objects.select_for_update()
        .filter(order=order, shipment__sequence=shipment_sequence, kind=KIND.DELIVERY, status=A.OUT_FOR_DELIVERY)
        .first()
    )
    if assignment is None:
        raise ConflictError(
            "A delivery code is only needed while the order is out for delivery.", code="otp_not_needed"
        )
    otp.reissue(assignment)
    tell_delivery_code(order, assignment)
    return assignment


# --- Cash ----------------------------------------------------------------------------------------


@transaction.atomic
def hand_over_cash(assignment_id: int, *, actor, note: str = "") -> DeliveryAssignment:
    """Store staff confirm they received the cash the rider collected for this delivery."""
    _order, assignment = _lock(assignment_id)
    if not assignment.cod_collected_at:
        raise ConflictError("No cash was collected for this delivery.", code="cod_not_collected")
    if assignment.cod_handed_over_at:
        raise ConflictError("This cash was already handed over.", code="cod_already_handed_over")
    assignment.cod_handed_over_at, assignment.cod_handed_over_to = timezone.now(), actor
    assignment.cod_handover_note = note.strip()[:255]
    assignment.save(update_fields=["cod_handed_over_at", "cod_handed_over_to", "cod_handover_note", "updated_at"])
    record_audit(
        action="delivery.cod_handover",
        actor=actor,
        target=assignment,
        changes={
            "order": assignment.order.order_number,
            "partner": assignment.partner_id,
            "amount": str(assignment.cod_collected_amount),
        },
    )
    return assignment
