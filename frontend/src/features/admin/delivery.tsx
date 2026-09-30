import { useState } from 'react'

import { ErrorState, Spinner } from '@/components/feedback'
import { Modal } from '@/components/Modal'
import { useToast } from '@/components/toast'

import { useAssignShipment, useEligiblePartners, useUnassignShipment } from './api'
import type { StaffShipment } from './types'
import { Badge, ConfirmDialog, errorMessage } from './ui'

/**
 * Choose a delivery partner for a shipment. The list comes from the server (only riders who may
 * take this shipment now); the assignment itself is checked again by the Phase 10 API.
 */
export function AssignRiderDialog({ shipment, onClose }: { shipment: StaffShipment | null; onClose: () => void }) {
  const partners = useEligiblePartners(shipment?.id ?? null)
  const assign = useAssignShipment()
  const toast = useToast()
  const [chosen, setChosen] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const [seen, setSeen] = useState<number | null>(null)
  if ((shipment?.id ?? null) !== seen) {
    setSeen(shipment?.id ?? null)
    setChosen(null)
    setReason('')
    assign.reset()
  }
  if (!shipment) return null
  const reassign = shipment.can_reassign

  function submit() {
    if (!shipment || chosen === null) return
    assign.mutate(
      { shipment: shipment.id, partner_id: chosen, reassign, reason },
      {
        onSuccess: () => {
          toast.show(`Order ${shipment.order_number} ${reassign ? 'reassigned' : 'assigned'}.`)
          onClose()
        },
      },
    )
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`${reassign ? 'Reassign' : 'Assign'} order ${shipment.order_number}`}
      footer={
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={assign.isPending}>
            Cancel
          </button>
          <button type="button" className="btn-primary" onClick={submit} disabled={chosen === null || assign.isPending}>
            {assign.isPending ? 'Assigning…' : reassign ? 'Reassign' : 'Assign'}
          </button>
        </div>
      }
    >
      <p className="mb-3 text-sm text-ink-600">
        From {shipment.store_name}
        {shipment.rider && reassign && <> · now with {shipment.rider.full_name}</>}
      </p>
      {partners.isPending ? (
        <Spinner label="Finding delivery partners…" />
      ) : partners.isError ? (
        <ErrorState error={partners.error} onRetry={() => void partners.refetch()} title="Couldn’t load delivery partners" />
      ) : partners.data.length === 0 ? (
        <p className="rounded-md bg-amber-100 px-3 py-2 text-sm">
          No delivery partner can take this shipment right now. Riders must be verified, online and have room for another job.
        </p>
      ) : (
        <fieldset>
          <legend className="label">Delivery partner</legend>
          <ul className="space-y-2">
            {partners.data.map((partner) => (
              <li key={partner.partner_id}>
                <label className="flex cursor-pointer items-center gap-3 rounded-md p-2.5 text-sm ring-1 ring-steel-200 has-checked:ring-2 has-checked:ring-amber-500">
                  <input
                    type="radio"
                    name="partner"
                    className="accent-amber-500"
                    checked={chosen === partner.partner_id}
                    onChange={() => setChosen(partner.partner_id)}
                  />
                  <span className="flex-1">
                    <span className="font-semibold">{partner.full_name}</span>
                    <span className="block text-xs text-ink-600">
                      {partner.vehicle_type} · {partner.active_assignments} of {partner.capacity} jobs
                      {partner.distance_km !== null && ` · ${partner.distance_km.toFixed(1)} km from the store`}
                    </span>
                  </span>
                  {partner.same_store && <Badge tone="good">This store</Badge>}
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      )}
      {reassign && (
        <div className="mt-3">
          <label htmlFor="reassign-reason" className="label">
            Reason (optional)
          </label>
          <input id="reassign-reason" className="input" maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
      )}
      {assign.isError && (
        <p role="alert" className="mt-3 rounded-md bg-danger-600/10 px-3 py-2 text-sm text-danger-600">
          {errorMessage(assign.error)}
        </p>
      )}
    </Modal>
  )
}

export function UnassignDialog({ shipment, onClose }: { shipment: StaffShipment | null; onClose: () => void }) {
  const unassign = useUnassignShipment()
  const toast = useToast()
  return (
    <ConfirmDialog
      open={shipment !== null}
      title={`Take order ${shipment?.order_number ?? ''} off the rider?`}
      confirmLabel="Unassign"
      danger
      busy={unassign.isPending}
      error={unassign.error}
      note={{ label: 'Reason (optional)' }}
      onClose={() => {
        unassign.reset()
        onClose()
      }}
      onConfirm={(reason) => {
        if (!shipment) return
        unassign.mutate(
          { shipment: shipment.id, reason },
          {
            onSuccess: () => {
              toast.show(`Order ${shipment.order_number} is waiting for a rider again.`)
              onClose()
            },
          },
        )
      }}
    >
      <p>
        {shipment?.rider?.full_name ?? 'The rider'} will no longer see this job. The shipment goes back to “waiting for a rider”.
      </p>
    </ConfirmDialog>
  )
}

/** Assign / reassign / unassign buttons of one shipment, as far as the server allows them. */
export function ShipmentActions({
  shipment,
  onAssign,
  onUnassign,
}: {
  shipment: StaffShipment
  onAssign: (shipment: StaffShipment) => void
  onUnassign: (shipment: StaffShipment) => void
}) {
  if (!shipment.can_assign && !shipment.can_reassign) return <span className="text-ink-600">—</span>
  return (
    <span className="flex flex-wrap justify-end gap-1.5 md:justify-start">
      <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => onAssign(shipment)}>
        {shipment.can_reassign ? 'Reassign' : 'Assign rider'}
        {' '}
<span className="sr-only">for order {shipment.order_number}</span>
      </button>
      {shipment.can_reassign && (
        <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => onUnassign(shipment)}>
          Unassign{' '}
<span className="sr-only">order {shipment.order_number}</span>
        </button>
      )}
    </span>
  )
}
