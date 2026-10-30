import { useEffect, useMemo, useState } from 'react'
import { Link, useOutletContext, useSearchParams } from 'react-router-dom'
import { Modal } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { useAuth } from '../context/AuthContext'
import { Api, errorMessage } from '../services/api'
import { fmtDateTime, fmtTime, fromLocalInput, humanize, toLocalInput } from '../services/format'

// Dispatcher electrician service catalog
export const UC_SERVICES = [
  // Switch & Socket
  {
    id: 'uc_sw_replace',
    category: 'switch_socket',
    categoryName: 'Switch & Socket',
    title: 'Switch / Socket Replacement & Repair',
    price: 89,
    originalPrice: 129,
    duration_minutes: 25,
    rating: 4.84,
    reviews: '24K',
    skills: ['residential_wiring'],
    tag: 'popular',
    icon: '🔌',
    description: 'Repair of spark, loose contacts, or replacement of burnt switch/socket unit.',
    features: [
      '30-day post-service warranty',
      'Circuit continuity & earth leakage test',
      'Procurement of branded spare parts on MRP with invoice',
      'Post-service cleanup included',
    ],
    inclusions: [
      'Inspection of faulty switch/socket',
      'Replacement/repair using standard tools',
      'Testing under electrical load',
    ],
    exclusions: ['Cost of replacement spare parts (billed at MRP)', 'Concealed wall chiseling/masonry'],
  },
  {
    id: 'uc_sw_board_inst',
    category: 'switch_socket',
    categoryName: 'Switch & Socket',
    title: 'Switchboard Installation (Up to 6 modules)',
    price: 199,
    originalPrice: 279,
    duration_minutes: 45,
    rating: 4.81,
    reviews: '12K',
    skills: ['residential_wiring'],
    tag: 'installation',
    icon: '🎛️',
    description: 'Complete assembly and installation of new modular switchboard with wiring connection.',
    features: [
      '30-day warranty on workmanship',
      'Safe phase, neutral & ground balancing',
      'Tested with digital multi-meter',
    ],
    inclusions: ['Fitting of gang box & modular plate', 'Internal jumper wiring', 'Full circuit load testing'],
    exclusions: ['Modular board materials', 'Wall plastering'],
  },
  {
    id: 'uc_ac_power_point',
    category: 'switch_socket',
    categoryName: 'Switch & Socket',
    title: 'AC / Heavy Appliance Power Point (16A / 25A)',
    price: 249,
    originalPrice: 329,
    duration_minutes: 45,
    rating: 4.88,
    reviews: '18K',
    skills: ['residential_wiring'],
    tag: 'installation',
    icon: '⚡',
    description: 'Dedicated 16A/25A heavy load socket setup with modular starter for AC, geyser or microwave.',
    features: [
      'High-gauge copper terminal connection',
      'Earth continuity verification',
      'Prevents overheating and voltage drop',
    ],
    inclusions: ['Installation of 16A/25A socket & enclosure', 'Load wire termination', 'Voltage testing'],
    exclusions: ['Heavy wiring beyond 2 meters (billed per meter)', 'Appliance repair'],
  },

  // Fans & Regulators
  {
    id: 'uc_fan_repair',
    category: 'fan',
    categoryName: 'Fan & Regulators',
    title: 'Ceiling Fan Repair & Regreasing',
    price: 149,
    originalPrice: 199,
    duration_minutes: 35,
    rating: 4.82,
    reviews: '38K',
    skills: ['residential_wiring', 'fault_finding'],
    tag: 'repair',
    icon: '🌀',
    description: 'Fixing slow speed, wobbling, bearing noise, or capacitor replacement for ceiling fans.',
    features: [
      'Capacitor & winding resistance check',
      'Complete lubrication and blade balancing',
      'Speed regulator calibration',
    ],
    inclusions: ['Dismantling & fault diagnosis', 'Capacitor replacement (labour)', 'Regreasing & re-hanging'],
    exclusions: ['Cost of capacitor/bearings if replaced', 'Fan motor rewinding (workshop service)'],
  },
  {
    id: 'uc_fan_installation',
    category: 'fan',
    categoryName: 'Fan & Regulators',
    title: 'Ceiling Fan Installation / Replacement',
    price: 199,
    originalPrice: 269,
    duration_minutes: 45,
    rating: 4.87,
    reviews: '29K',
    skills: ['residential_wiring'],
    tag: 'installation',
    icon: '🌀',
    description: 'Assembling and mounting of new ceiling fan with secure downrod shackle bolt and canopy.',
    features: [
      'Heavy-duty ceiling hook anchor testing',
      'Precision blade angle alignment',
      'Noise-free balanced spin check',
    ],
    inclusions: ['Assembly of motor, downrod, blades', 'Secure ceiling mounting', 'Connection to regulator'],
    exclusions: ['Ceiling hook drilling (if not present)', 'Scaffolding for double-height ceilings'],
  },
  {
    id: 'uc_bldc_fan',
    category: 'fan',
    categoryName: 'Fan & Regulators',
    title: 'Smart BLDC Fan Installation & Remote Pairing',
    price: 299,
    originalPrice: 399,
    duration_minutes: 60,
    rating: 4.91,
    reviews: '9.4K',
    skills: ['smart_home', 'residential_wiring'],
    tag: 'popular',
    icon: '✨',
    description: 'Expert installation of energy-efficient BLDC fan with RF remote pairing and smart IoT setup.',
    features: [
      'Direct-drive BLDC PCB circuit protection',
      'Bypass of old mechanical regulator',
      'WiFi / remote control sync & demo',
    ],
    inclusions: ['Complete installation', 'Mechanical regulator bypass', 'Remote / app setup'],
    exclusions: ['Cost of smart fan unit', 'WiFi router troubleshooting'],
  },
  {
    id: 'uc_exhaust_fan',
    category: 'fan',
    categoryName: 'Fan & Regulators',
    title: 'Exhaust Fan Installation / Replacement',
    price: 179,
    originalPrice: 229,
    duration_minutes: 35,
    rating: 4.79,
    reviews: '8.1K',
    skills: ['residential_wiring'],
    tag: 'installation',
    icon: '💨',
    description: 'Mounting and electrical wiring for kitchen or bathroom ventilation fan.',
    features: ['Vibration-dampened fitting', 'Sealed wiring connection', 'Louver check'],
    inclusions: ['Mounting in pre-cut wall opening', 'Wiring to nearest switch', 'Operation test'],
    exclusions: ['Glass cutting or civil brick cutting', 'Exhaust unit cost'],
  },

  // Lights & Chandelier
  {
    id: 'uc_tube_light',
    category: 'light',
    categoryName: 'Lights & Chandelier',
    title: 'Tube Light / LED Batten Installation',
    price: 99,
    originalPrice: 149,
    duration_minutes: 20,
    rating: 4.85,
    reviews: '41K',
    skills: ['lighting'],
    tag: 'popular',
    icon: '💡',
    description: 'Drilling, clamp fixing, and electrical connection for LED batten or tube light.',
    features: ['Precision laser leveling', 'Sturdy wall anchors', 'Neat concealed connection'],
    inclusions: ['Drilling and wall plugs', 'Wiring connection', 'Testing'],
    exclusions: ['Light fixture cost', 'External wiring longer than 1m'],
  },
  {
    id: 'uc_chandelier_small',
    category: 'light',
    categoryName: 'Lights & Chandelier',
    title: 'Chandelier Installation (Up to 5 Arms / Hanging)',
    price: 499,
    originalPrice: 699,
    duration_minutes: 75,
    rating: 4.89,
    reviews: '5.2K',
    skills: ['lighting'],
    tag: 'installation',
    icon: '✨',
    description: 'Assembly, crystal hanging, and ceiling anchor load-bearing installation for decorative chandeliers.',
    features: [
      'High-tensile anchor fastener installation',
      'Delicate crystal handling with cotton gloves',
      'Dimmer & multi-bulb circuit testing',
    ],
    inclusions: ['Structural hook test', 'Assembly of frame & crystals', 'Complete wiring & illumination'],
    exclusions: ['Chandelier fixture & bulbs', 'Double-height scaffolding'],
  },
  {
    id: 'uc_downlight_cob',
    category: 'light',
    categoryName: 'Lights & Chandelier',
    title: 'False Ceiling Spot / COB Downlight Installation',
    price: 129,
    originalPrice: 179,
    duration_minutes: 30,
    rating: 4.83,
    reviews: '16K',
    skills: ['lighting'],
    tag: 'installation',
    icon: '🔆',
    description: 'Spring-clamp installation of round/square recessed LED panel or spotlight in false ceiling.',
    features: ['Flush fit without gyproc chipping', 'Driver transformer safety tie', 'Phase matching'],
    inclusions: ['Connection to existing false ceiling wiring', 'Spring clamp fitting', 'Testing'],
    exclusions: ['Gypsum hole cutting', 'New driver unit cost'],
  },

  // Wiring & MCB
  {
    id: 'uc_mcb_tripping',
    category: 'wiring_mcb',
    categoryName: 'Wiring & MCB',
    title: 'MCB Tripping & Short Circuit Diagnostics',
    price: 249,
    originalPrice: 349,
    duration_minutes: 45,
    rating: 4.86,
    reviews: '22K',
    skills: ['fault_finding', 'panel_upgrade'],
    tag: 'repair',
    icon: '⚠️',
    description: 'Systematic fault-finding to locate short circuits, neutral loop leaks, or overloaded breakers.',
    features: [
      'Digital insulation resistance & megger testing',
      'Branch-by-branch isolation',
      'Overload calculation and safety assessment',
    ],
    inclusions: ['Full board testing', 'Fault location identification', 'Temporary restoration or minor fix'],
    exclusions: ['Full house rewiring', 'Cost of replacement MCB/RCCB'],
  },
  {
    id: 'uc_mcb_replacement',
    category: 'wiring_mcb',
    categoryName: 'Wiring & MCB',
    title: 'Single / Double Pole MCB Replacement',
    price: 169,
    originalPrice: 229,
    duration_minutes: 30,
    rating: 4.82,
    reviews: '11K',
    skills: ['panel_upgrade'],
    tag: 'repair',
    icon: '🎛️',
    description: 'Replacement of faulty, burnt, or weak miniature circuit breaker in main distribution board.',
    features: ['DIN-rail snap-fit mounting', 'Torque-tightened terminal screws', 'Ampere rating verification'],
    inclusions: ['Disconnection and removal of faulty MCB', 'Installation of new MCB', 'Busbar connection'],
    exclusions: ['Cost of MCB breaker', 'Distribution board box replacement'],
  },
  {
    id: 'uc_db_board',
    category: 'wiring_mcb',
    categoryName: 'Wiring & MCB',
    title: 'Distribution Board / Main Panel Replacement',
    price: 799,
    originalPrice: 1099,
    duration_minutes: 90,
    rating: 4.93,
    reviews: '4.8K',
    skills: ['panel_upgrade', 'residential_wiring'],
    tag: 'upgrade',
    icon: '⚡',
    description: 'Complete overhaul of old fuse/switch box with modern 4-way to 8-way TPN/SPN distribution box.',
    features: [
      'Neat wire dressing and neutral link balancing',
      'Proper earth busbar bonding',
      'Circuit label tagging for easy identification',
    ],
    inclusions: ['De-wiring old box', 'Mounting new metal DB enclosure', 'Re-routing circuits with MCBs'],
    exclusions: ['Cost of DB enclosure & MCBs', 'Concealed wall masonry patching'],
  },
  {
    id: 'uc_internal_wiring',
    category: 'wiring_mcb',
    categoryName: 'Wiring & MCB',
    title: 'Concealed / Casing Wiring (Per 5 Metres)',
    price: 299,
    originalPrice: 399,
    duration_minutes: 60,
    rating: 4.81,
    reviews: '14K',
    skills: ['residential_wiring'],
    tag: 'installation',
    icon: '🧵',
    description: 'Pulling flame-retardant multi-strand copper wire through conduits or surface casing.',
    features: ['FR PVC insulated wiring', 'Zero sagging secure saddle fixing', 'Safe load rating'],
    inclusions: ['Labour for 5m wiring run', 'Connection at both ends', 'Continuity testing'],
    exclusions: ['Wire & casing material costs', 'Civil wall channel cutting'],
  },

  // Inverter, Solar & EV
  {
    id: 'uc_ev_charger',
    category: 'appliance_solar',
    categoryName: 'Inverter & EV',
    title: 'EV Home Charger Installation & Dedicated Earthing',
    price: 699,
    originalPrice: 949,
    duration_minutes: 90,
    rating: 4.94,
    reviews: '3.1K',
    skills: ['ev_charger', 'panel_upgrade'],
    tag: 'popular',
    icon: '🚗',
    description: 'Professional setup of 3.3kW to 7.4kW EV wallbox or 16A heavy-duty outdoor charging socket.',
    features: [
      'Low-resistance earth pit continuity verification (<2 ohms)',
      'Dedicated DP MCB & RCCB isolation protection',
      'Continuous load safety rating certificate',
    ],
    inclusions: ['Wall mounting of charging station', 'DB connection with protection breaker', 'Initial charge test'],
    exclusions: ['Armoured cable cost (>3m)', 'Dedicated earth electrode installation'],
  },
  {
    id: 'uc_inverter_setup',
    category: 'appliance_solar',
    categoryName: 'Inverter & EV',
    title: 'Inverter & Battery Wiring & Installation',
    price: 449,
    originalPrice: 599,
    duration_minutes: 60,
    rating: 4.88,
    reviews: '19K',
    skills: ['solar_pv', 'panel_upgrade'],
    tag: 'installation',
    icon: '🔋',
    description: 'Wiring of home backup inverter, battery terminals with petroleum jelly, and bypass switch.',
    features: [
      'Heavy copper battery lead crimping',
      'Phase isolation to prevent reverse power feed',
      'Mains cut-off automatic switchover test',
    ],
    inclusions: ['Inverter positioning & wiring', 'Battery terminal connection', 'Load separation (lights/fans)'],
    exclusions: ['Inverter & battery unit', 'Battery water replenishment'],
  },
  {
    id: 'uc_solar_check',
    category: 'appliance_solar',
    categoryName: 'Inverter & EV',
    title: 'Solar PV Inverter Inspection & Net Metering Check',
    price: 799,
    originalPrice: 1099,
    duration_minutes: 90,
    rating: 4.91,
    reviews: '2.4K',
    skills: ['solar_pv', 'inspection_testing'],
    tag: 'upgrade',
    icon: '☀️',
    description: 'Comprehensive check of rooftop solar string voltage, grid inverter sync, and net meter wiring.',
    features: ['DC string open-circuit voltage verification', 'Inverter efficiency & MPPT check', 'Isolator switch test'],
    inclusions: ['Full solar inverter audit', 'Earth leakage check', 'Generation report review'],
    exclusions: ['Rooftop solar panel replacement', 'Utility net-meter application'],
  },

  // Smart Home & Security
  {
    id: 'uc_video_doorbell',
    category: 'smart_security',
    categoryName: 'Smart Home',
    title: 'Video Doorbell Installation & Mobile Sync',
    price: 349,
    originalPrice: 479,
    duration_minutes: 45,
    rating: 4.87,
    reviews: '6.7K',
    skills: ['smart_home', 'data_cabling'],
    tag: 'popular',
    icon: '🔔',
    description: 'Drilling, mounting, transformer wiring, chime integration, and WiFi configuration for smart doorbell.',
    features: ['Tamper-resistant mounting', 'AC transformer step-down check', 'Live audio & video cloud setup'],
    inclusions: ['Mounting on doorframe/wall', 'Wiring to existing power source', 'Smartphone app pairing'],
    exclusions: ['Doorbell hardware', 'Door chime hardware'],
  },
  {
    id: 'uc_smart_switch_wifi',
    category: 'smart_security',
    categoryName: 'Smart Home',
    title: 'Smart WiFi Touch Switch Panel Setup',
    price: 399,
    originalPrice: 529,
    duration_minutes: 50,
    rating: 4.89,
    reviews: '7.8K',
    skills: ['smart_home', 'residential_wiring'],
    tag: 'upgrade',
    icon: '📱',
    description: 'Installation of touch smart switchboard, neutral line routing, and Alexa / Google Home integration.',
    features: ['Capacitive touch calibration', 'Neutral wire verification in switchbox', 'Automation scene programming'],
    inclusions: ['Smart panel wiring', 'App pairing & scene configuration', 'Voice assistant sync'],
    exclusions: ['Smart switch hardware', 'Extensive neutral wire re-pulling (>3m)'],
  },

  // Full Home Inspection & Audit
  {
    id: 'uc_home_audit',
    category: 'inspection',
    categoryName: 'Full Home Audit',
    title: 'Full Home Electrical Safety Audit & Load Testing',
    price: 399,
    originalPrice: 599,
    duration_minutes: 60,
    rating: 4.95,
    reviews: '31K',
    skills: ['inspection_testing', 'fault_finding'],
    tag: 'popular',
    icon: '📋',
    description: 'End-to-end electrical inspection: earthing resistance, MCB health, voltage balance & fire safety check.',
    features: [
      'Comprehensive 24-point electrical health report',
      'Infrared thermal detection for overheating connections',
      'Earth pit resistance test with digital meter',
      'Appliance surge protection recommendations',
    ],
    inclusions: ['Inspection of all switchboards & DB', 'Earthing check', 'Written digital health report'],
    exclusions: ['Repairs or spare parts (can be added on actuals)'],
  },
  {
    id: 'uc_industrial_audit',
    category: 'inspection',
    categoryName: 'Full Home Audit',
    title: 'Commercial / 3-Phase Industrial Panel Audit',
    price: 999,
    originalPrice: 1399,
    duration_minutes: 120,
    rating: 4.96,
    reviews: '1.8K',
    skills: ['industrial_wiring', 'inspection_testing', 'high_voltage'],
    tag: 'upgrade',
    icon: '🏭',
    description: 'Three-phase load balancing, harmonic distortion check, transformer inspection, and safety sign-off.',
    features: ['Phase angle & power factor measurement', 'Busbar contact resistance', 'Relay tripping simulation'],
    inclusions: ['3-phase panel inspection', 'Thermal imaging of busbars', 'Compliance audit document'],
    exclusions: ['Transformer oil replacement', 'Utility liaison'],
  },
  {
    id: 'uc_consultation_visit',
    category: 'inspection',
    categoryName: 'Full Home Audit',
    title: 'Electrician Doorstep Consultation & Diagnosis',
    price: 99,
    originalPrice: 149,
    duration_minutes: 30,
    rating: 4.82,
    reviews: '54K',
    skills: ['fault_finding'],
    tag: 'repair',
    icon: '🔍',
    description: 'Doorstep visit by certified electrician to inspect custom electrical problems and provide estimate.',
    features: [
      'Inspection fee adjusted against final service bill if work is approved',
      'Upfront transparent quotation',
      'No hidden charges',
    ],
    inclusions: ['On-site physical inspection', 'Diagnosis and quote generation'],
    exclusions: ['Major repair labour (quoted separately)'],
  },
]

export const CATEGORIES = [
  { id: 'switch_socket', name: 'Switch & socket', spriteCol: 0, spriteRow: 0 },
  { id: 'fan', name: 'Fan', spriteCol: 1, spriteRow: 0 },
  { id: 'light', name: 'Light', spriteCol: 2, spriteRow: 0 },
  { id: 'wiring', name: 'Wiring', spriteCol: 3, spriteRow: 0 },
  { id: 'doorbell_security', name: 'Doorbell & security', spriteCol: 0, spriteRow: 1 },
  { id: 'mcb_fuse', name: 'MCB/fuse', spriteCol: 1, spriteRow: 1 },
  { id: 'appliances', name: 'Appliances', spriteCol: 2, spriteRow: 1 },
  { id: 'consultation', name: 'Book a consultation', spriteCol: 3, spriteRow: 1 },
]

function categoryForService(service) {
  let id = service.category
  if (service.category === 'wiring_mcb') {
    id = service.id === 'uc_internal_wiring' ? 'wiring' : 'mcb_fuse'
  } else if (service.category === 'smart_security') {
    id = 'doorbell_security'
  } else if (service.category === 'appliance_solar') {
    id = 'appliances'
  } else if (service.category === 'inspection') {
    id = 'consultation'
  }
  return CATEGORIES.find((category) => category.id === id) || CATEGORIES[0]
}

function spritePosition(category) {
  const horizontal = ['0%', '33.333%', '66.667%', '100%'][category.spriteCol]
  const vertical = category.spriteRow === 0 ? '16.667%' : '83.333%'
  return `${horizontal} ${vertical}`
}

export const TIME_SLOTS = [
  { id: 'slot_morning', label: '09:00 AM – 11:00 AM', startH: 9, endH: 11 },
  { id: 'slot_midday', label: '11:30 AM – 01:30 PM', startH: 11, endH: 13.5 },
  { id: 'slot_afternoon', label: '02:00 PM – 04:00 PM', startH: 14, endH: 16 },
  { id: 'slot_evening', label: '04:30 PM – 06:30 PM', startH: 16.5, endH: 18.5 },
  { id: 'slot_night', label: '07:00 PM – 09:00 PM', startH: 19, endH: 21 },
]

export default function ServiceCart() {
  const [searchParams] = useSearchParams()
  const { bump, location } = useOutletContext() || { bump: () => {}, location: null }
  const { user } = useAuth()
  const toast = useToast()

  // URL state
  const urlQuery = searchParams.get('q') || ''

  // Cart & UI state
  const [cart, setCart] = useState({}) // { [serviceId]: qty }
  const [selectedCat, setSelectedCat] = useState(urlQuery ? 'all' : 'switch_socket')
  const [searchQuery, setSearchQuery] = useState(urlQuery)
  const [detailItem, setDetailItem] = useState(null)

  useEffect(() => {
    if (urlQuery) {
      setSearchQuery(urlQuery)
      setSelectedCat('all')
    }
  }, [urlQuery])

  // Booking drawer state
  const [selectedDate, setSelectedDate] = useState('tomorrow') // 'today' | 'tomorrow' | 'day_after'
  const [selectedSlot, setSelectedSlot] = useState(TIME_SLOTS[0].id)
  const [selectedZone, setSelectedZone] = useState('CEN')
  const [priority, setPriority] = useState('medium') // 'medium' (Standard) | 'urgent' (Priority dispatch)
  const [customerName, setCustomerName] = useState(user?.display_name || '')
  const [customerPhone, setCustomerPhone] = useState('')
  const [customerAddress, setCustomerAddress] = useState('')
  const [serviceLocality, setServiceLocality] = useState('')
  const [couponCode, setCouponCode] = useState('DISPATCH10')
  const [appliedCoupon, setAppliedCoupon] = useState('DISPATCH10')

  // API Data
  const [zones, setZones] = useState([])
  const [skills, setSkills] = useState([])
  const [busyBooking, setBusyBooking] = useState(false)
  const [confirmedBooking, setConfirmedBooking] = useState(null)

  useEffect(() => {
    if (!serviceLocality && location) setServiceLocality(location.city || location.district || '')
  }, [location, serviceLocality])

  // Load zones & skills
  useEffect(() => {
    Api.zones().then(setZones).catch(() => {})
    Api.skills().then(setSkills).catch(() => {})
  }, [])

  useEffect(() => {
    if (user?.role !== 'customer' || !location || !zones.length || !Number.isFinite(location.lat) || !Number.isFinite(location.lon)) return
    const closest = [...zones].sort((a, b) =>
      ((a.center_lat - location.lat) ** 2 + (a.center_lon - location.lon) ** 2) -
      ((b.center_lat - location.lat) ** 2 + (b.center_lon - location.lon) ** 2),
    )[0]
    if (closest) setSelectedZone(closest.code)
  }, [user?.role, location, zones])

  // Calculate cart items & totals
  const cartEntries = useMemo(() => {
    return Object.entries(cart)
      .filter(([, qty]) => qty > 0)
      .map(([id, qty]) => {
        const item = UC_SERVICES.find((s) => s.id === id)
        return { item, qty, total: (item?.price || 0) * qty }
      })
      .filter((entry) => Boolean(entry.item))
  }, [cart])

  const cartItemCount = cartEntries.reduce((sum, e) => sum + e.qty, 0)
  const itemSubtotal = cartEntries.reduce((sum, e) => sum + e.total, 0)
  const visitingFee = itemSubtotal >= 399 || itemSubtotal === 0 ? 0 : 49
  const discountAmount = appliedCoupon === 'DISPATCH10' ? Math.round(itemSubtotal * 0.1) : appliedCoupon === 'FIRST100' ? Math.min(100, itemSubtotal) : 0
  const totalAmount = Math.max(0, itemSubtotal + visitingFee - discountAmount)

  // Cart operations
  const updateQty = (id, delta) => {
    setCart((prev) => {
      const current = prev[id] || 0
      const next = Math.max(0, current + delta)
      if (next === 0) {
        const copy = { ...prev }
        delete copy[id]
        return copy
      }
      return { ...prev, [id]: next }
    })
  }

  // Filtered services
  const displayedServices = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return UC_SERVICES.filter((s) => {
      if (selectedCat !== 'all' && categoryForService(s).id !== selectedCat) return false
      if (q) {
        const text = `${s.title} ${s.description} ${s.categoryName} ${s.skills.join(' ')}`.toLowerCase()
        return text.includes(q)
      }
      return true
    })
  }, [selectedCat, searchQuery])

  const activeCategory = CATEGORIES.find((category) => category.id === selectedCat) || {
    id: 'all',
    name: 'All electrician services',
  }

  // Booking Execution
  const handleBookNow = async () => {
    if (cartItemCount === 0) {
      toast('Please add at least one electrician service to your cart', 'error')
      return
    }
    if (!location?.district || !location?.state) {
      toast('Choose a district and state for the service location first', 'error')
      return
    }
    if (!customerAddress.trim() || !serviceLocality.trim()) {
      toast('Enter your service locality and full address', 'error')
      return
    }
    if (!location?.district || !location?.state) {
      toast('Select your district and state in the location selector', 'error')
      return
    }

    setBusyBooking(true)
    try {
      // 1. Calculate combined duration and union of skills
      let combinedDuration = 0
      const skillsSet = new Set()
      const titles = []

      cartEntries.forEach(({ item, qty }) => {
        combinedDuration += (item.duration_minutes || 30) * qty
        item.skills.forEach((sk) => skillsSet.add(sk))
        titles.push(`${item.title}${qty > 1 ? ` (x${qty})` : ''}`)
      })

      // Duration capped between 30 and 360 mins
      const durationMinutes = Math.min(360, Math.max(30, combinedDuration))
      const requiredSkills = Array.from(skillsSet)

      // 2. Compute planning dates
      const baseDate = new Date()
      if (selectedDate === 'tomorrow') {
        baseDate.setDate(baseDate.getDate() + 1)
      } else if (selectedDate === 'day_after') {
        baseDate.setDate(baseDate.getDate() + 2)
      }

      const slotObj = TIME_SLOTS.find((s) => s.id === selectedSlot) || TIME_SLOTS[0]
      const winStart = new Date(baseDate)
      winStart.setHours(Math.floor(slotObj.startH), (slotObj.startH % 1) * 60, 0, 0)

      const winEnd = new Date(baseDate)
      winEnd.setHours(Math.floor(slotObj.endH), (slotObj.endH % 1) * 60, 0, 0)

      const slaDeadline = new Date(winEnd)
      slaDeadline.setHours(slaDeadline.getHours() + 2) // SLA 2h after window

      // Prefer the selected map/GPS coordinates. Manual district/state entries use the
      // configured dispatch zone center because they do not include map coordinates.
      const zObj = zones.find((z) => z.code === selectedZone)
      const lat = Number.isFinite(location.lat) ? location.lat : (zObj?.center_lat || 28.6139)
      const lon = Number.isFinite(location.lon) ? location.lon : (zObj?.center_lon || 77.209)
      const serviceLocation = `${location.district}, ${location.state}`

      const payload = {
        title: titles.slice(0, 2).join(' + ') + (titles.length > 2 ? ` + ${titles.length - 2} more` : ''),
        customer_name: customerName,
        customer_phone: customerPhone.trim() || null,
        address: `${customerAddress.trim()}, ${serviceLocality.trim()}, ${serviceLocation}`,
        service_locality: serviceLocality.trim(),
        district: location.district,
        state: location.state,
        service_category: [...new Set(cartEntries.map(({ item }) => item.categoryName))].join(', '),
        booking_amount: totalAmount,
        service_items: cartEntries.map(({ item, qty }) => ({ id: item.id, quantity: qty })),
        coupon_code: appliedCoupon || null,
        description: `Dispatcher electrician booking in ${serviceLocation}. Services: ${titles.join(', ')}. Bill: ₹${totalAmount}`,
        zone_code: selectedZone,
        priority: priority,
        duration_minutes: durationMinutes,
        required_skills: requiredSkills.length > 0 ? requiredSkills : ['residential_wiring'],
        lat: Number(lat.toFixed(6)),
        lon: Number(lon.toFixed(6)),
        window_start: fromLocalInput(toLocalInput(winStart)),
        window_end: fromLocalInput(toLocalInput(winEnd)),
        sla_deadline: fromLocalInput(toLocalInput(slaDeadline)),
      }

      // 3. Create the job in DispatchGrid
      const createdJob = await Api.createJob(payload)
      toast(`Booking ${createdJob.job_number} created successfully!`, 'success')

      // Customer bookings dispatch automatically on the server; dispatcher bookings use the existing run action.
      const run = user?.role === 'customer' ? null : await Api.runScheduling()
      bump()

      // 5. Fetch assigned job details
      let scheduleInfo = null
      if (user?.role === 'customer') {
        scheduleInfo = { current_assignment: createdJob.assignment, unassigned_reasons: createdJob.unassigned_reasons }
      } else {
        try {
          scheduleInfo = await Api.jobSchedule(createdJob.id)
        } catch (err) {
          // Fallback if not ready
        }
      }

      setConfirmedBooking({
        job: createdJob,
        assignment: scheduleInfo?.current_assignment || null,
        unassigned_reasons: scheduleInfo?.unassigned_reasons || [],
        explanation: scheduleInfo?.explanation || null,
        metrics: run?.metrics,
        totalAmount,
        itemCount: cartItemCount,
        slot: slotObj.label,
        date: fmtDateTime(winStart).split(' ')[0],
      })

      // Clear cart
      setCart({})
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setBusyBooking(false)
    }
  }

  return (
    <div className="uc-cart-page">
      <div className="uc-subbar">
        <div className="uc-subbar-container">
          <div className="uc-breadcrumbs">
            <Link to="/">Home</Link>
            <span className="sep">/</span>
            <span className="loc">{location ? `${location.district}, ${location.state}` : 'Choose a service location'}</span>
            <span className="sep">/</span>
            <span className="cat-crumb">Electrician Services</span>
          </div>
          <div className="uc-city-pill">
            <span className="dot active" />
            <span>{location ? <>Service district: <b>{location.district}, {location.state}</b></> : 'No service location selected'}</span>
          </div>
        </div>
      </div>

      {/* Service categories, matching plans, and cart */}
      <div className="uc-layout-grid service-booking-layout">
        <aside className="uc-cat-sidebar">
          <div className="uc-sidebar-sticky service-category-panel">
            <div className="sidebar-heading">Select a service</div>
            <nav className="service-category-grid" aria-label="Electrician service categories">
              {CATEGORIES.map((category) => (
                <button
                  key={category.id}
                  type="button"
                  className={`service-category-tile ${selectedCat === category.id ? 'selected' : ''}`}
                  aria-pressed={selectedCat === category.id}
                  onClick={() => {
                    setSelectedCat(category.id)
                    setSearchQuery('')
                  }}
                >
                  <span
                    className="service-category-image service-sprite"
                    style={{ backgroundPosition: spritePosition(category) }}
                    aria-hidden="true"
                  />
                  <span className="service-category-name">{category.name}</span>
                </button>
              ))}
            </nav>
          </div>
        </aside>

        <main className="uc-catalog-column">
          <div className="service-plan-heading">
            <div>
              <h1>{activeCategory.name}</h1>
              <p>Choose a service plan to add it to your cart.</p>
            </div>
          </div>

          <div className="catalog-status-line">
            <span><b>{displayedServices.length}</b> {displayedServices.length === 1 ? 'service plan' : 'service plans'}{location ? ` in ${location.district}` : ''}</span>
            {searchQuery && (
              <button className="btn ghost small reset-cat" onClick={() => { setSearchQuery(''); setSelectedCat('switch_socket') }}>
                Clear search
              </button>
            )}
          </div>

          {/* Service Cards Grid */}
          <div className="uc-services-list">
            {displayedServices.length === 0 ? (
              <div className="uc-empty-search">
                <div className="empty-emoji">🔍</div>
                <h3>No electrician service matched &ldquo;{searchQuery}&rdquo;</h3>
                <p>Try searching for fan, switchboard, wiring, MCB, or reset filters.</p>
                <button className="btn primary small" onClick={() => { setSearchQuery(''); setSelectedCat('switch_socket') }}>
                  Browse services
                </button>
              </div>
            ) : (
              displayedServices.map((svc) => {
                const qty = cart[svc.id] || 0
                const serviceCategory = categoryForService(svc)
                return (
                  <article key={svc.id} className="uc-service-card">
                    <div className="service-info">
                      <div className="service-title-row">
                        <h3 className="service-title">{svc.title}</h3>
                        {svc.tag === 'popular' && <span className="uc-badge-bestseller">Bestseller</span>}
                      </div>

                      <div className="service-meta">
                        <span className="rating-pill">
                          ★ {svc.rating} <span className="rev">({svc.reviews})</span>
                        </span>
                        <span className="dot">•</span>
                        <span className="duration-tag">⏱️ {svc.duration_minutes} mins</span>
                        <span className="dot">•</span>
                        <span className="warranty-tag">🛡️ 30-day warranty</span>
                      </div>

                      <div className="service-pricing">
                        <span className="price-current">₹{svc.price}</span>
                        {svc.originalPrice && (
                          <span className="price-mrp">₹{svc.originalPrice}</span>
                        )}
                        <span className="discount-tag">
                          {Math.round(((svc.originalPrice - svc.price) / svc.originalPrice) * 100)}% OFF
                        </span>
                      </div>

                      <p className="service-desc">{svc.description}</p>

                      <ul className="service-highlights">
                        {svc.features.slice(0, 2).map((feat, idx) => (
                          <li key={idx}>
                            <span className="check-icon">✓</span> {feat}
                          </li>
                        ))}
                      </ul>

                      <div className="service-card-foot">
                        <button
                          type="button"
                          className="btn-details-link"
                          onClick={() => setDetailItem(svc)}
                        >
                          View inclusions &amp; details ➔
                        </button>
                      </div>
                    </div>

                    <div className="service-action-column">
                      <div
                        className="service-icon-box service-sprite service-plan-image"
                        style={{ backgroundPosition: spritePosition(serviceCategory) }}
                        role="img"
                        aria-label={`${serviceCategory.name} service`}
                      />

                      {/* Add button or Quantity Stepper */}
                      <div className="service-stepper-wrap">
                        {qty === 0 ? (
                          <button
                            type="button"
                            className="btn-add-uc"
                            onClick={() => updateQty(svc.id, 1)}
                          >
                            + ADD
                          </button>
                        ) : (
                          <div className="uc-stepper">
                            <button
                              type="button"
                              className="step-btn"
                              onClick={() => updateQty(svc.id, -1)}
                              aria-label="Decrease quantity"
                            >
                              −
                            </button>
                            <span className="step-val">{qty}</span>
                            <button
                              type="button"
                              className="step-btn"
                              onClick={() => updateQty(svc.id, 1)}
                              aria-label="Increase quantity"
                            >
                              +
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  </article>
                )
              })
            )}
          </div>
        </main>

        {/* Right column: booking cart and dispatch panel */}
        <aside className="uc-cart-column">
          <div className="service-side-offer">
            <span className="offer-icon" aria-hidden="true">%</span>
            <div>
              <strong>Get the visit fee waived</strong>
              <small>On orders above ₹399</small>
            </div>
          </div>
          <section className="service-promise-card" aria-label="Dispatcher promise">
            <h3>Dispatcher Promise</h3>
            <ul>
              <li>✓ Verified professionals</li>
              <li>✓ Hassle-free booking</li>
              <li>✓ Transparent pricing</li>
            </ul>
          </section>
          <div className="uc-cart-sticky-card">
            <div className="cart-card-header">
              <div className="cart-title">
                <span className="cart-icon">🛒</span>
                <h3>My Cart</h3>
                {cartItemCount > 0 && <span className="cart-count-badge">{cartItemCount}</span>}
              </div>
              {cartItemCount > 0 && (
                <button
                  type="button"
                  className="btn ghost small clear-btn"
                  onClick={() => setCart({})}
                >
                  Clear
                </button>
              )}
            </div>

            {cartItemCount === 0 ? (
              <div className="uc-cart-empty">
                <div className="empty-cart-art" aria-hidden="true">🛒</div>
                <p>No items in your cart</p>
              </div>
            ) : (
              <div className="uc-cart-filled">
                {/* Itemized List */}
                <div className="cart-items-scroll">
                  {cartEntries.map(({ item, qty, total }) => (
                    <div key={item.id} className="cart-line-item">
                      <div className="line-item-main">
                        <div className="line-item-name">{item.title}</div>
                        <div className="line-item-rate">₹{item.price} × {qty}</div>
                      </div>
                      <div className="line-item-actions">
                        <div className="uc-stepper mini">
                          <button
                            type="button"
                            className="step-btn"
                            onClick={() => updateQty(item.id, -1)}
                          >
                            −
                          </button>
                          <span className="step-val">{qty}</span>
                          <button
                            type="button"
                            className="step-btn"
                            onClick={() => updateQty(item.id, 1)}
                          >
                            +
                          </button>
                        </div>
                        <span className="line-total">₹{total}</span>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Scheduling: Date & Slot Selector */}
                <div className="uc-booking-section">
                  <div className="section-head">
                    <span className="sec-icon">📅</span>
                    <h4>Select Service Date &amp; Slot</h4>
                  </div>

                  <div className="uc-date-tabs">
                    <button
                      type="button"
                      className={`date-tab ${selectedDate === 'today' ? 'active' : ''}`}
                      onClick={() => setSelectedDate('today')}
                    >
                      <span>Today</span>
                      <small>Priority visit</small>
                    </button>
                    <button
                      type="button"
                      className={`date-tab ${selectedDate === 'tomorrow' ? 'active' : ''}`}
                      onClick={() => setSelectedDate('tomorrow')}
                    >
                      <span>Tomorrow</span>
                      <small>Recommended</small>
                    </button>
                    <button
                      type="button"
                      className={`date-tab ${selectedDate === 'day_after' ? 'active' : ''}`}
                      onClick={() => setSelectedDate('day_after')}
                    >
                      <span>Day After</span>
                      <small>Flexible</small>
                    </button>
                  </div>

                  <div className="uc-slots-grid">
                    {TIME_SLOTS.map((slot) => (
                      <button
                        key={slot.id}
                        type="button"
                        className={`slot-chip ${selectedSlot === slot.id ? 'active' : ''}`}
                        onClick={() => setSelectedSlot(slot.id)}
                      >
                        {slot.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Service address and dispatch zone */}
                <div className="uc-booking-section">
                  <div className="section-head">
                    <span className="sec-icon">📍</span>
                    <h4>Service address</h4>
                  </div>

                  <div className={`service-location-summary ${location ? 'is-selected' : ''}`}>
                    <strong>{location ? `${location.district}, ${location.state}` : 'Choose your district and state'}</strong>
                    <span>{location ? (location.source === 'gps' ? 'Detected from your current location' : location.source === 'map' ? 'Selected from location search' : 'Entered manually') : 'Use the location selector in the header to search, select, or detect your location.'}</span>
                  </div>

                  {user?.role !== 'customer' && <div className="zone-dropdown-wrap">
                    <label className="field-lbl">Dispatch zone</label>
                    <select
                      value={selectedZone}
                      onChange={(e) => setSelectedZone(e.target.value)}
                      className="uc-select"
                    >
                      {zones.map((z) => (
                        <option key={z.code} value={z.code}>
                          {z.name} ({z.code})
                        </option>
                      ))}
                    </select>
                    <small className="field-hint">Used by the current dispatcher schedule to check local electrician availability.</small>
                  </div>}

                  <div className="customer-fields">
                    <input
                      type="text"
                      placeholder="Locality or neighbourhood"
                      value={serviceLocality}
                      onChange={(e) => setServiceLocality(e.target.value)}
                      className="uc-input"
                    />
                    <input
                      type="text"
                      placeholder="Your Name"
                      value={customerName}
                      onChange={(e) => setCustomerName(e.target.value)}
                      className="uc-input"
                    />
                    <input
                      type="tel"
                      placeholder="Mobile Number"
                      value={customerPhone}
                      onChange={(e) => setCustomerPhone(e.target.value)}
                      className="uc-input"
                    />
                    <textarea
                      rows={2}
                      placeholder="Flat, House no., Building, Street address"
                      value={customerAddress}
                      onChange={(e) => setCustomerAddress(e.target.value)}
                      className="uc-input"
                    />
                  </div>

                  <div className="priority-toggle-row">
                    <label className="prio-opt">
                      <input
                        type="radio"
                        name="priority"
                        checked={priority === 'medium'}
                        onChange={() => setPriority('medium')}
                      />
                      <span>Standard Slot (Medium SLA)</span>
                    </label>
                    <label className="prio-opt urgent">
                      <input
                        type="radio"
                        name="priority"
                        checked={priority === 'urgent'}
                        onChange={() => setPriority('urgent')}
                      />
                        <span>⚡ Urgent (Priority dispatch)</span>
                    </label>
                  </div>
                </div>

                {/* Coupon Box */}
                <div className="uc-coupon-card">
                  <div className="coupon-row">
                    <span className="c-icon">🏷️</span>
                    <input
                      type="text"
                      placeholder="Coupon Code"
                      value={couponCode}
                      onChange={(e) => setCouponCode(e.target.value.toUpperCase())}
                      className="coupon-input"
                    />
                    <button
                      type="button"
                      className="btn-apply-coupon"
                      onClick={() => {
                        if (couponCode === 'DISPATCH10' || couponCode === 'FIRST100') {
                          setAppliedCoupon(couponCode)
                          toast(`Coupon ${couponCode} applied!`, 'success')
                        } else {
                          toast('Invalid coupon code. Try DISPATCH10 or FIRST100', 'error')
                        }
                      }}
                    >
                      Apply
                    </button>
                  </div>
                  {appliedCoupon && (
                    <div className="coupon-applied-msg">
                      <span>✓ <b>{appliedCoupon}</b> applied — ₹{discountAmount} saved!</span>
                      <button
                        className="btn-remove-coupon"
                        onClick={() => { setAppliedCoupon(null); setCouponCode('') }}
                      >
                        Remove
                      </button>
                    </div>
                  )}
                  <div className="coupon-pills">
                    <button
                      type="button"
                      className="coupon-quick-pill"
                      onClick={() => { setCouponCode('DISPATCH10'); setAppliedCoupon('DISPATCH10') }}
                    >
                      DISPATCH10 (10% OFF)
                    </button>
                    <button
                      type="button"
                      className="coupon-quick-pill"
                      onClick={() => { setCouponCode('FIRST100'); setAppliedCoupon('FIRST100') }}
                    >
                      FIRST100 (₹100 OFF)
                    </button>
                  </div>
                </div>

                {/* Bill Details */}
                <div className="uc-bill-details">
                  <div className="bill-heading">Payment Summary</div>
                  <div className="bill-row">
                    <span>Item Total</span>
                    <span>₹{itemSubtotal}</span>
                  </div>
                  <div className="bill-row">
                    <span>Visiting &amp; Safety Fee</span>
                    <span>
                      {visitingFee === 0 ? (
                        <span className="free-badge">FREE</span>
                      ) : (
                        `₹${visitingFee}`
                      )}
                    </span>
                  </div>
                  {discountAmount > 0 && (
                    <div className="bill-row discount">
                      <span>Coupon Discount</span>
                      <span>−₹{discountAmount}</span>
                    </div>
                  )}
                  <div className="bill-row total">
                    <span>To Pay</span>
                    <span className="final-sum">₹{totalAmount}</span>
                  </div>
                  {discountAmount > 0 && (
                    <div className="uc-savings-banner">
                      🎉 Yay! You saved ₹{discountAmount} on this booking!
                    </div>
                  )}
                </div>

                {/* Primary CTA Button */}
                <div className="uc-checkout-action">
                  <button
                    type="button"
                    className="btn-book-now-uc"
                    disabled={busyBooking || cartItemCount === 0}
                    onClick={handleBookNow}
                  >
                    {busyBooking ? (
                      <span className="booking-spinner">Booking &amp; Dispatching Electrician…</span>
                    ) : (
                      <>
                        <span>Book Electrician Now • ₹{totalAmount}</span>
                        <span className="arrow">➔</span>
                      </>
                    )}
                  </button>
                  <p className="uc-cancellation-note">
                    🛡️ Free cancellation up to 2 hours before the slot. 100% money back guarantee.
                  </p>
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>

      {/* Booking Confirmation Modal */}
      {confirmedBooking && (
        <Modal
          title="Booking Confirmed!"
          onClose={() => setConfirmedBooking(null)}
          wide
        >
          <div className="uc-booking-success">
            <div className="success-header">
              <div className="success-badge-icon">✓</div>
              <h2>Electrician Dispatched &amp; Scheduled!</h2>
              <p className="success-sub">
                Your service has been confirmed with Dispatcher.
              </p>
            </div>

            <div className="uc-confirmed-card">
              <div className="confirm-row">
                <span className="lbl">Booking Reference</span>
                <span className="val highlight">{confirmedBooking.job.job_number}</span>
              </div>
              <div className="confirm-row">
                <span className="lbl">Service Details</span>
                <span className="val">{confirmedBooking.job.title}</span>
              </div>
              <div className="confirm-row">
                <span className="lbl">Customer Address</span>
                <span className="val">{confirmedBooking.job.address}</span>
              </div>
              <div className="confirm-row">
                <span className="lbl">Appointment Slot</span>
                <span className="val">{confirmedBooking.date} • {confirmedBooking.slot}</span>
              </div>
              <div className="confirm-row">
                <span className="lbl">Total Paid</span>
                <span className="val price">₹{confirmedBooking.totalAmount}</span>
              </div>
            </div>

            {/* Assignment Status Box */}
            {confirmedBooking.assignment ? (
              <div className="assigned-electrician-box">
                <div className="electrician-avatar">👷</div>
                <div className="electrician-details">
                  <div className="badge-assigned">Assigned Electrician</div>
                  <h3>{confirmedBooking.assignment.electrician_name}</h3>
                  <p className="eta-text">
                    Scheduled Arrival: <b>{fmtDateTime(confirmedBooking.assignment.start)}</b> to <b>{fmtTime(confirmedBooking.assignment.end)}</b>
                  </p>
                  {confirmedBooking.explanation && (
                    <p className="small muted">{confirmedBooking.explanation}</p>
                  )}
                </div>
              </div>
            ) : (
              <div className="unassigned-notice-box">
                <div className="notice-icon">⏱️</div>
                <div>
                  <h4>Optimizing Best Route &amp; Electrician</h4>
                  <p>Your job is in the active scheduling pool. Dispatcher is matching it with a qualified technician in your selected dispatch zone.</p>
                </div>
              </div>
            )}

            <div className="success-actions">
              <Link
                to="/schedule"
                className="btn primary"
                onClick={() => setConfirmedBooking(null)}
              >
                View Live Schedule Timeline ➔
              </Link>
              <Link
                to="/jobs"
                className="btn"
                onClick={() => setConfirmedBooking(null)}
              >
                View in Jobs Roster
              </Link>
              <button
                type="button"
                className="btn ghost"
                onClick={() => setConfirmedBooking(null)}
              >
                Book Another Service
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* Service Details & Inclusions Modal */}
      {detailItem && (
        <Modal
          title={detailItem.title}
          onClose={() => setDetailItem(null)}
          wide
        >
          <div className="uc-details-modal-body">
            <div className="modal-hero-row">
              <div className="modal-title-wrap">
                <div className="meta-pills">
                  <span className="rating-pill">★ {detailItem.rating} ({detailItem.reviews})</span>
                  <span className="duration-tag">⏱️ {detailItem.duration_minutes} mins</span>
                  <span className="cat-chip">{detailItem.categoryName}</span>
                </div>
                <h3>{detailItem.title}</h3>
                <p className="modal-desc">{detailItem.description}</p>
                <div className="modal-pricing">
                  <span className="price-current">₹{detailItem.price}</span>
                  {detailItem.originalPrice && (
                    <span className="price-mrp">₹{detailItem.originalPrice}</span>
                  )}
                  <span className="discount-tag">
                    {Math.round(((detailItem.originalPrice - detailItem.price) / detailItem.originalPrice) * 100)}% OFF
                  </span>
                </div>
              </div>
              <div className="modal-thumb-box">
                <span className="modal-emoji">{detailItem.icon}</span>
              </div>
            </div>

            <div className="modal-inclusions-grid">
              <div className="inclusion-box">
                <h4>✓ What is Included</h4>
                <ul>
                  {detailItem.inclusions.map((inc, i) => (
                    <li key={i}>{inc}</li>
                  ))}
                  <li>30-day post-service warranty on workmanship</li>
                  <li>Complete cleanup of electrical debris &amp; insulation clippings</li>
                </ul>
              </div>

              <div className="exclusion-box">
                <h4>✕ What is Excluded</h4>
                <ul>
                  {detailItem.exclusions.map((exc, i) => (
                    <li key={i}>{exc}</li>
                  ))}
                  <li>Civil masonry, tile cutting, or repainting work</li>
                </ul>
              </div>
            </div>

            <div className="modal-faq-section">
              <h4>Frequently Asked Questions</h4>
              <div className="faq-item">
                <b>Will the electrician bring the replacement switches or wires?</b>
                <p>Yes, electricians carry standard branded spares (Anchor, Havells, Schneider, Polycab). Spare parts are charged on MRP with an official invoice.</p>
              </div>
              <div className="faq-item">
                <b>What if the problem recurs after the service?</b>
                <p>Dispatcher covers eligible repairs with a 30-day workmanship warranty. If a covered issue recurs, request a rework visit through support.</p>
              </div>
            </div>

            <div className="modal-footer-action">
              <button
                type="button"
                className="btn-add-uc modal-btn"
                onClick={() => {
                  updateQty(detailItem.id, 1)
                  setDetailItem(null)
                  toast(`${detailItem.title} added to cart`, 'success')
                }}
              >
                + Add Service to Cart (₹{detailItem.price})
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
