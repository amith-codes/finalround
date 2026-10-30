import { Link } from 'react-router-dom'

const ACTIONS = [
  { to: '/cart?category=electrician_density', title: 'Book an appointment', copy: 'Choose a service, locality and time that works for you.', icon: '⚡' },
  { to: '/bookings', title: 'Track booking status', copy: 'See your electrician, appointment details and updates.', icon: '⌖' },
  { to: '/payments', title: 'Payment methods', copy: 'View and manage your saved payment references.', icon: '₹' },
]

export default function CustomerHome() {
  return (
    <div className="stack customer-home">
      <div className="page-head"><div><h1>Welcome to Dispatcher</h1><p className="muted">What would you like to do today?</p></div></div>
      <div className="customer-action-grid">
        {ACTIONS.map((action) => <Link className="customer-action-card" key={action.to} to={action.to}>
          <span className="customer-action-icon">{action.icon}</span>
          <span><b>{action.title}</b><small>{action.copy}</small></span>
          <span className="customer-action-arrow">›</span>
        </Link>)}
      </div>
    </div>
  )
}
