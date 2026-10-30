const NOMINATIM_URL = 'https://nominatim.openstreetmap.org'
const locationCache = new Map()
let lastRequestAt = 0
let requestQueue = Promise.resolve()

export const INDIAN_STATES = [
  'Andaman and Nicobar Islands',
  'Andhra Pradesh',
  'Arunachal Pradesh',
  'Assam',
  'Bihar',
  'Chandigarh',
  'Chhattisgarh',
  'Dadra and Nagar Haveli and Daman and Diu',
  'Delhi',
  'Goa',
  'Gujarat',
  'Haryana',
  'Himachal Pradesh',
  'Jammu and Kashmir',
  'Jharkhand',
  'Karnataka',
  'Kerala',
  'Ladakh',
  'Lakshadweep',
  'Madhya Pradesh',
  'Maharashtra',
  'Manipur',
  'Meghalaya',
  'Mizoram',
  'Nagaland',
  'Odisha',
  'Puducherry',
  'Punjab',
  'Rajasthan',
  'Sikkim',
  'Tamil Nadu',
  'Telangana',
  'Tripura',
  'Uttar Pradesh',
  'Uttarakhand',
  'West Bengal',
]

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function requestNominatim(url, cacheKey) {
  if (locationCache.has(cacheKey)) return locationCache.get(cacheKey)

  const request = requestQueue.then(async () => {
    if (locationCache.has(cacheKey)) return locationCache.get(cacheKey)
    const pause = Math.max(0, 1100 - (Date.now() - lastRequestAt))
    if (pause) await wait(pause)

    lastRequestAt = Date.now()
    const response = await fetch(url, {
      headers: { 'Accept-Language': 'en' },
    })
    if (!response.ok) throw new Error('Location search is unavailable right now. Please try again or enter the district and state manually.')

    const result = await response.json()
    locationCache.set(cacheKey, result)
    return result
  })
  requestQueue = request.catch(() => {})
  return request
}

function normalizeResult(result) {
  const address = result.address || {}
  const city = address.city || address.town || address.village || address.municipality || address.suburb || ''
  const district = address.state_district || address.county || address.district || address.city_district || address.municipality || city || ''
  const state = address.state || ''
  const districtAndState = [district, state].filter(Boolean)
  const displayName = [...new Set(districtAndState)].join(', ') || result.display_name || 'Selected location'
  const area = [city, district !== city ? district : '', state].filter(Boolean)

  return {
    district,
    state,
    city,
    postcode: address.postcode || '',
    displayName,
    areaLabel: [...new Set(area)].join(', ') || displayName,
    lat: Number(result.lat),
    lon: Number(result.lon),
    source: 'map',
  }
}

export async function searchIndianLocations(query) {
  const params = new URLSearchParams({
    q: `${query.trim()}, India`,
    countrycodes: 'in',
    format: 'jsonv2',
    addressdetails: '1',
    limit: '6',
  })
  const results = await requestNominatim(`${NOMINATIM_URL}/search?${params}`, `search:${query.trim().toLowerCase()}`)
  return results
    .filter((item) => item.address?.country_code === 'in' || item.address?.country?.toLowerCase() === 'india')
    .map(normalizeResult)
    .filter((item) => item.district && item.state)
}

export async function reverseGeocode({ latitude, longitude }) {
  const lat = Number(latitude.toFixed(4))
  const lon = Number(longitude.toFixed(4))
  const params = new URLSearchParams({
    lat: String(latitude),
    lon: String(longitude),
    format: 'jsonv2',
    addressdetails: '1',
    zoom: '8',
  })
  const result = await requestNominatim(`${NOMINATIM_URL}/reverse?${params}`, `reverse:${lat},${lon}`)
  if (result.address?.country_code !== 'in') {
    throw new Error('Your current location is outside India. Search or enter an Indian district and state instead.')
  }
  const location = normalizeResult(result)
  if (!location.district || !location.state) {
    throw new Error('We could not identify the district and state for this location. Search for them or enter them manually.')
  }
  return { ...location, lat: latitude, lon: longitude, source: 'gps' }
}
