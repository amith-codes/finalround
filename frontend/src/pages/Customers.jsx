import { useEffect, useState } from 'react'
import { Api, errorMessage } from '../services/api'
import { useToast } from '../context/ToastContext'
import { Card, Empty, ErrorBox, Loading } from '../components/ui'

export default function Customers() {
  const toast = useToast()
  const [customers, setCustomers] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ display_name: '', username: '', password: '' })
  const load = async () => {
    try { setCustomers(await Api.adminCustomers()); setError(null) }
    catch (e) { setError(errorMessage(e)) }
  }
  useEffect(() => { load() }, [])
  const create = async (e) => {
    e.preventDefault(); setBusy(true)
    try { await Api.createCustomer(form); setForm({ display_name: '', username: '', password: '' }); toast('Customer account created', 'success'); await load() }
    catch (e) { toast(errorMessage(e), 'error') }
    finally { setBusy(false) }
  }
  if (!customers && !error) return <Loading what="Loading customers" />
  return <div className="stack">
    <div className="page-head"><div><h1>Customers</h1><p className="muted">Customer accounts use the same sign-in screen as every role.</p></div></div>
    <ErrorBox error={error} />
    <Card title="Customer accounts">
      {!customers?.length ? <Empty>No customer accounts have been provisioned.</Empty> : <div className="table-wrap"><table className="table"><thead><tr><th>Customer</th><th>Sign-in</th><th>Bookings</th></tr></thead><tbody>{customers.map((customer) => <tr key={customer.id}><td><b>{customer.display_name}</b></td><td>{customer.username}</td><td>{customer.booking_count}</td></tr>)}</tbody></table></div>}
    </Card>
    <Card title="Provision a customer account">
      <form className="form" onSubmit={create}>
        <label>Customer name<input required minLength={2} value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></label>
        <label>Sign-in name<input required minLength={3} autoComplete="off" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
        <label>Temporary password<input required minLength={8} type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
        <div className="span2"><button className="btn primary" disabled={busy}>{busy ? 'Creating…' : 'Create customer'}</button></div>
      </form>
    </Card>
  </div>
}
