import { useEffect, useState } from 'react'
import { Api, errorMessage } from '../services/api'
import { useToast } from '../context/ToastContext'
import { Card, Empty, ErrorBox, Loading } from '../components/ui'

export default function PaymentMethods() {
  const toast = useToast()
  const [methods, setMethods] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ label: '', brand: 'Visa', last4: '' })
  const load = async () => {
    try { setMethods(await Api.paymentMethods()); setError(null) }
    catch (e) { setError(errorMessage(e)) }
  }
  useEffect(() => { load() }, [])
  const add = async (event) => {
    event.preventDefault(); setBusy(true)
    try {
      await Api.addPaymentMethod({ ...form, is_default: methods.length === 0 })
      setForm({ label: '', brand: 'Visa', last4: '' }); toast('Payment method saved', 'success'); await load()
    } catch (e) { toast(errorMessage(e), 'error') } finally { setBusy(false) }
  }
  const remove = async (method) => {
    try { await Api.removePaymentMethod(method.id); toast('Payment method removed', 'success'); await load() }
    catch (e) { toast(errorMessage(e), 'error') }
  }
  const setDefault = async (method) => {
    try { await Api.setDefaultPaymentMethod(method.id); toast('Default payment method updated', 'success'); await load() }
    catch (e) { toast(errorMessage(e), 'error') }
  }
  if (!methods && !error) return <Loading what="Loading payment methods" />
  return <div className="stack customer-portal-page">
    <div className="page-head"><div><h1>Payment methods</h1><p className="muted">Manage the masked payment references on your account.</p></div></div>
    <ErrorBox error={error} />
    <Card title="Saved methods">
      {!methods?.length ? <Empty>No saved payment methods yet.</Empty> : <div className="payment-method-list">
        {methods.map((method) => <div className="payment-method-row" key={method.id}>
          <span className="payment-card-mark">{method.brand.slice(0, 1).toUpperCase()}</span>
          <span><b>{method.label}</b><small>{method.brand} ending in {method.last4}{method.is_default ? ' · Default' : ''}</small></span>
          {!method.is_default && <button className="btn small" onClick={() => setDefault(method)}>Set default</button>}
          <button className="btn small danger" onClick={() => remove(method)}>Remove</button>
        </div>)}
      </div>}
    </Card>
    <Card title="Add a payment method">
      <form className="form payment-method-form" onSubmit={add}>
        <label>Label<input required maxLength={80} placeholder="Personal card" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} /></label>
        <label>Card brand<select value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })}><option>Visa</option><option>Mastercard</option><option>RuPay</option><option>Amex</option><option>UPI</option></select></label>
        <label>Last four digits<input required inputMode="numeric" pattern="[0-9]{4}" maxLength={4} placeholder="1234" value={form.last4} onChange={(e) => setForm({ ...form, last4: e.target.value.replace(/\D/g, '').slice(0, 4) })} /></label>
        <div className="span2"><button className="btn primary" disabled={busy}>{busy ? 'Saving…' : 'Save payment reference'}</button></div>
      </form>
      <p className="muted small payment-note">This demo stores only the label, brand and last four digits. It does not charge cards or save full card details.</p>
    </Card>
  </div>
}
