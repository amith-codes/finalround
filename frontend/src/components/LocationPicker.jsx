import { useState } from 'react'
import { INDIAN_STATES, reverseGeocode, searchIndianLocations } from '../services/location'

export default function LocationPicker({ location, onSelect }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [locating, setLocating] = useState(false)
  const [manualOpen, setManualOpen] = useState(false)
  const [district, setDistrict] = useState('')
  const [state, setState] = useState('')
  const [message, setMessage] = useState('')

  const chooseLocation = (value) => {
    onSelect(value)
    setOpen(false)
    setQuery('')
    setResults([])
    setMessage('')
  }

  const search = async (event) => {
    event.preventDefault()
    if (!query.trim()) return

    setSearching(true)
    setMessage('')
    setResults([])
    try {
      const matches = await searchIndianLocations(query)
      setResults(matches)
      if (!matches.length) setMessage('No matching Indian district found. Try a nearby city or enter the district and state manually.')
    } catch (error) {
      setMessage(error.message || 'Could not search locations. Please enter the district and state manually.')
    } finally {
      setSearching(false)
    }
  }

  const detectCurrentLocation = () => {
    if (!navigator.geolocation) {
      setMessage('Location detection is not available in this browser. Search or enter the district and state manually.')
      return
    }

    setLocating(true)
    setMessage('Allow location access in your browser to detect your district and state.')
    navigator.geolocation.getCurrentPosition(
      async ({ coords }) => {
        try {
          const detected = await reverseGeocode({ latitude: coords.latitude, longitude: coords.longitude })
          chooseLocation(detected)
        } catch (error) {
          setMessage(error.message || 'Could not identify your district and state. Search or enter them manually.')
        } finally {
          setLocating(false)
        }
      },
      (error) => {
        const messageByCode = {
          1: 'Location access was denied. Search or enter your district and state instead.',
          2: 'Your current location could not be determined. Try again or enter the district and state manually.',
          3: 'Location detection took too long. Try again or enter the district and state manually.',
        }
        setMessage(messageByCode[error.code] || 'Location detection failed. Search or enter the district and state manually.')
        setLocating(false)
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 },
    )
  }

  const saveManualLocation = async (event) => {
    event.preventDefault()
    if (!district.trim() || !state) {
      setMessage('Enter a district and select a state or union territory.')
      return
    }

    setSearching(true)
    try {
      const matches = await searchIndianLocations(`${district.trim()}, ${state}`)
      const match = matches.find((item) => item.state.toLowerCase() === state.toLowerCase())
      if (match) {
        chooseLocation(match)
      } else {
        chooseLocation({
          district: district.trim(),
          state,
          city: '',
          postcode: '',
          displayName: `${district.trim()}, ${state}`,
          areaLabel: `${district.trim()}, ${state}`,
          lat: null,
          lon: null,
          source: 'manual',
        })
      }
    } catch {
      chooseLocation({
        district: district.trim(),
        state,
        city: '',
        postcode: '',
        displayName: `${district.trim()}, ${state}`,
        areaLabel: `${district.trim()}, ${state}`,
        lat: null,
        lon: null,
        source: 'manual',
      })
    } finally {
      setSearching(false)
    }
  }

  return (
    <div className="uc-location-selector">
      <button
        type="button"
        className="location-btn"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => { setOpen((value) => !value); setMessage('') }}
      >
        <span className="loc-pin" aria-hidden="true">⌖</span>
        <span className="loc-info">
          <span className="loc-city">SERVICE LOCATION</span>
          <span className="loc-area">{location?.areaLabel || 'Select district & state'} <span aria-hidden="true">⌄</span></span>
        </span>
      </button>

      {open && (
        <section className="location-dropdown" role="dialog" aria-label="Choose service location">
          <div className="loc-drop-title">Set your service location</div>
          <p className="loc-drop-copy">Choose an area in India or detect your current district and state.</p>

          <button type="button" className="loc-current-button" onClick={detectCurrentLocation} disabled={locating}>
            <span className="loc-current-icon" aria-hidden="true">◎</span>
            <span>{locating ? 'Detecting your location…' : 'Use my current location'}</span>
          </button>

          <form className="loc-search-form" onSubmit={search}>
            <label htmlFor="location-search">Search area, district, or PIN code</label>
            <div className="loc-search-row">
              <input
                id="location-search"
                type="search"
                placeholder="For example, Jaipur or Mysuru"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              <button type="submit" disabled={searching || !query.trim()}>{searching ? 'Searching…' : 'Search'}</button>
            </div>
          </form>

          {results.length > 0 && (
            <div className="loc-results" aria-label="Location search results">
              {results.map((result, index) => (
                <button key={`${result.displayName}-${index}`} type="button" className="loc-result" onClick={() => chooseLocation(result)}>
                  <span className="loc-result-pin" aria-hidden="true">⌖</span>
                  <span>
                    <strong>{result.district}, {result.state}</strong>
                    <small>{result.areaLabel}{result.postcode ? ` · ${result.postcode}` : ''}</small>
                  </span>
                </button>
              ))}
            </div>
          )}

          {message && <p className="loc-message" role="status">{message}</p>}

          <button type="button" className="loc-manual-toggle" onClick={() => { setManualOpen((value) => !value); setMessage('') }}>
            {manualOpen ? 'Hide manual entry' : 'Enter district and state manually'}
          </button>

          {manualOpen && (
            <form className="loc-manual-form" onSubmit={saveManualLocation}>
              <label htmlFor="manual-district">District</label>
              <input id="manual-district" value={district} onChange={(event) => setDistrict(event.target.value)} placeholder="Enter district name" />
              <label htmlFor="manual-state">State or union territory</label>
              <select id="manual-state" value={state} onChange={(event) => setState(event.target.value)}>
                <option value="">Choose state or union territory</option>
                {INDIAN_STATES.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
              <button type="submit" className="loc-save-button" disabled={searching}>{searching ? 'Saving…' : 'Save location'}</button>
              <small>We’ll look up the district center for route planning. If it can’t be found, the district and state will still be saved.</small>
            </form>
          )}

          <p className="loc-attribution">
            With GPS, coordinates are sent to OpenStreetMap to resolve your district and state. Location search and address lookup by{' '}
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>.
          </p>
        </section>
      )}
    </div>
  )
}
