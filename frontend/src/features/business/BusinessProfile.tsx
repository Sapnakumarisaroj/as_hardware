import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { FormField } from '@/components/FormField'
import { Modal } from '@/components/Modal'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import { api } from '@/lib/api/client'
import { ApiError } from '@/lib/api/errors'

export type BuyerType = 'individual' | 'carpenter' | 'contractor' | 'interior_designer' | 'business'

const BUYER_TYPE_LABELS: Record<BuyerType, string> = {
  individual: 'Home / individual',
  carpenter: 'Carpenter',
  contractor: 'Contractor',
  interior_designer: 'Interior designer',
  business: 'Business',
}

/** What the customer says they are (self-declared) and the details printed on their invoices. */
export interface BusinessProfile {
  buyer_type: BuyerType
  business_name: string
  gstin: string
}

const profileKey = ['profile'] as const

function useBusinessProfile() {
  const { status } = useAuth()
  return useQuery({
    queryKey: profileKey,
    queryFn: async () => (await api.get<BusinessProfile>('/profile/')).data,
    enabled: status === 'authenticated',
  })
}

function useSaveBusinessProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: BusinessProfile) => (await api.patch<BusinessProfile>('/profile/', input)).data,
    onSuccess: (profile) => {
      queryClient.setQueryData(profileKey, profile)
      void queryClient.invalidateQueries({ queryKey: ['quotes'] })
    },
  })
}

function BusinessForm({ profile, onClose }: { profile: BusinessProfile; onClose: () => void }) {
  const save = useSaveBusinessProfile()
  const toast = useToast()
  const [buyerType, setBuyerType] = useState<BuyerType>(profile.buyer_type)
  const error = save.error instanceof ApiError ? save.error : null
  const fieldError = (name: string) => error?.fieldErrors()[name]?.[0]

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    save.mutate(
      {
        buyer_type: buyerType,
        business_name: String(form.get('business_name') ?? '').trim(),
        gstin: String(form.get('gstin') ?? '').trim(),
      },
      {
        onSuccess: () => {
          toast.show('Business details saved')
          onClose()
        },
      },
    )
  }

  return (
    <Modal open onClose={onClose} title="Business details">
      <form onSubmit={submit} className="space-y-3" noValidate>
        <fieldset>
          <legend className="label">I am buying as</legend>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(BUYER_TYPE_LABELS) as BuyerType[]).map((type) => (
              <label
                key={type}
                className="flex min-h-11 cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm ring-1 ring-steel-200 has-checked:bg-amber-100 has-checked:ring-amber-500"
              >
                <input
                  type="radio"
                  name="buyer_type"
                  value={type}
                  checked={buyerType === type}
                  onChange={() => setBuyerType(type)}
                  className="accent-amber-600"
                />
                {BUYER_TYPE_LABELS[type]}
              </label>
            ))}
          </div>
        </fieldset>
        <FormField
          id="business_name"
          label="Business name"
          defaultValue={profile.business_name}
          maxLength={150}
          error={fieldError('business_name')}
          hint="Legal or trade name, printed on your invoices"
        />
        <FormField
          id="gstin"
          label="GSTIN"
          defaultValue={profile.gstin}
          maxLength={20}
          autoCapitalize="characters"
          error={fieldError('gstin')}
          hint="Optional. 15 characters, e.g. 29ABCDE1234F1ZW. We check the format only."
        />
        {error && !Object.keys(error.fieldErrors()).length && (
          <p role="alert" className="rounded-md bg-danger-600/10 px-3 py-2 text-sm text-danger-600">
            {error.message}
          </p>
        )}
        <div className="flex gap-2 pt-1">
          <button type="button" onClick={onClose} className="btn-secondary flex-1">
            Cancel
          </button>
          <button type="submit" disabled={save.isPending} className="btn-primary flex-1">
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Account page card: buyer type, business name and GSTIN, with an edit dialog. */
export function BusinessProfileCard() {
  const profile = useBusinessProfile()
  const [editing, setEditing] = useState(false)
  if (!profile.data) return null
  const data = profile.data
  return (
    <section aria-labelledby="business-heading" className="mt-4 rounded-2xl bg-white p-5 text-sm shadow-(--shadow-card) ring-1 ring-steel-200">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="business-heading" className="text-base font-bold">
          Business details
        </h2>
        <button type="button" onClick={() => setEditing(true)} className="font-semibold text-amber-700 hover:underline">
          Edit<span className="sr-only"> business details</span>
        </button>
      </div>
      <dl className="mt-2 grid gap-2 sm:grid-cols-3">
        <div>
          <dt className="text-ink-600">Buying as</dt>
          <dd className="font-medium">{BUYER_TYPE_LABELS[data.buyer_type] ?? data.buyer_type}</dd>
        </div>
        <div>
          <dt className="text-ink-600">Business name</dt>
          <dd className="font-medium">{data.business_name || '—'}</dd>
        </div>
        <div>
          <dt className="text-ink-600">GSTIN</dt>
          <dd className="font-medium">{data.gstin || '—'}</dd>
        </div>
      </dl>
      <p className="mt-2 text-xs text-ink-600">
        Buying in bulk for a project? Request a quote from your cart. Your business name and GSTIN go
        on your invoices.
      </p>
      {editing && <BusinessForm profile={data} onClose={() => setEditing(false)} />}
    </section>
  )
}
