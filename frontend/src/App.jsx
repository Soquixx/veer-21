import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity, AlertCircle, AlertTriangle, ArrowDownRight, ArrowRight,
  Bell, Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, CircleHelp,
  Clock3, Cloud, Compass, Database, Download, FileClock, Filter, Gauge, Layers3,
  LayoutDashboard, LogOut, MapPinned, Menu, Plane, Plus, Radio, RefreshCw,
  RotateCcw, Search, Send, Settings2, ShieldCheck, SlidersHorizontal, Sparkles,
  Target, Users, Wifi, X, Zap, Eye, EyeOff
} from 'lucide-react'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || window.VEER_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')
const NAV = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'missions', label: 'Mission board', icon: Target },
  { id: 'replanning', label: 'Scenario lab', icon: RefreshCw },
  { id: 'readiness', label: 'Readiness & feeds', icon: Radio },
  { id: 'history', label: 'Decision history', icon: FileClock },
  { id: 'evaluation', label: 'Performance', icon: Gauge },
]
const pretty = (s = '') => String(s).toLowerCase().replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase())
const friendlyType = (s = '') => ({ 'FIGHTER-A': 'Air support', 'TRANSPORT-B': 'Transport', 'HELO-C': 'Helicopter', 'ISR-D': 'Surveillance' }[s] || pretty(s))
const slots = n => `${Math.floor((Number(n || 0) * 15) / 60)}h ${String((Number(n || 0) * 15) % 60).padStart(2, '0')}m`
const fmt = n => Number(n || 0).toLocaleString()

async function request(path, token, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(options.headers || {}) },
  })
  const text = await response.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!response.ok) {
    const detail = data?.detail
    throw new Error(typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : `Request failed (${response.status})`)
  }
  return data
}

function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('veer_token') || '')
  const [role, setRole] = useState(() => sessionStorage.getItem('veer_role') || '')
  const [username, setUsername] = useState(() => sessionStorage.getItem('veer_user') || '')
  const [loginForm, setLoginForm] = useState({ username: '', password: '' })
  const [loginBusy, setLoginBusy] = useState(false)
  const [loginError, setLoginError] = useState('')
  const [active, setActive] = useState('overview')
  const [scenarios, setScenarios] = useState([])
  const [scenarioVersions, setScenarioVersions] = useState([])
  const [scenarioId, setScenarioId] = useState('')
  const [current, setCurrent] = useState(null)
  const [provenance, setProvenance] = useState(null)
  const [history, setHistory] = useState([])
  const [evaluation, setEvaluation] = useState(null)
  const [workspaceLoading, setWorkspaceLoading] = useState(() => Boolean(sessionStorage.getItem('veer_token')))
  const [events, setEvents] = useState([])
  const [impact, setImpact] = useState(null)
  const [replanResult, setReplanResult] = useState(null)
  const [job, setJob] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState('all')
  const [selectedMission, setSelectedMission] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({ name: '', size: 'M', tightness: 0.9, seed: 7, trap_groups: 0 })
  const [showEventForm, setShowEventForm] = useState(false)
  const [eventForm, setEventForm] = useState({ type: 'WEATHER', time: 15, sector: 'BRAVO', severity: 4, duration: 12 })
  const [manualEvents, setManualEvents] = useState([])
  const [selectedOption, setSelectedOption] = useState('')
  const [decisionReason, setDecisionReason] = useState('')
  const [health, setHealth] = useState(null)
  const [mobileNav, setMobileNav] = useState(false)
  const [entryView, setEntryView] = useState(() => window.location.hash === '#workspace' ? 'login' : 'landing')

  const call = useCallback((path, options) => request(path, token, options), [token])
  const loadScenarios = useCallback(async (preferred) => {
    const list = await call('/api/scenarios')
    setScenarios(list)
    const next = preferred || scenarioId || list[0]?.id || ''
    if (next && list.some(s => s.id === next)) setScenarioId(next)
    else if (list[0]) setScenarioId(list[0].id)
    else { setScenarioId(''); setCurrent(null) }
    return list
  }, [call, scenarioId])
  const loadCurrent = useCallback(async (id = scenarioId) => {
    if (!id) return null
    const [cur] = await Promise.all([call(`/api/scenarios/${id}/current`), call(`/health`).then(setHealth).catch(() => setHealth({ status: 'offline' }))])
    setCurrent(cur)
    setSelectedMission(null)
    setImpact(null)
    setReplanResult(null)
    setEvents([])
    setManualEvents([])
    return cur
  }, [call, scenarioId])
  const loadSupporting = useCallback(async (id = scenarioId) => {
    if (!id) return
    const tasks = await Promise.allSettled([
      call(`/api/provenance?scenario_id=${encodeURIComponent(id)}`),
      call(`/api/decisions/${encodeURIComponent(id)}`),
      call('/api/evaluation'),
      call(`/api/scenarios/${encodeURIComponent(id)}`)
    ])
    if (tasks[0].status === 'fulfilled') setProvenance(tasks[0].value)
    if (tasks[1].status === 'fulfilled') setHistory(tasks[1].value)
    if (tasks[2].status === 'fulfilled') setEvaluation(tasks[2].value)
    if (tasks[3].status === 'fulfilled') setScenarioVersions(tasks[3].value?.versions || [])
  }, [call, scenarioId])
  const refreshAll = useCallback(async (id = scenarioId) => {
    setError('')
    setWorkspaceLoading(true)
    try {
      const list = await loadScenarios(id)
      const preferredId = id && list.some(item => item.id === id) ? id : ''
      const currentId = preferredId || (scenarioId && list.some(item => item.id === scenarioId) ? scenarioId : '')
      const targetId = currentId || list[0]?.id || ''
      if (!targetId) {
        setScenarioId('')
        setCurrent(null)
        setProvenance(null)
        setHistory([])
        setScenarioVersions([])
        setEvaluation(null)
        setHealth({ status: 'ok' })
        return
      }
      setScenarioId(targetId)
      await Promise.all([loadCurrent(targetId), loadSupporting(targetId)])
    } catch (e) {
      setError(e.message)
    } finally {
      setWorkspaceLoading(false)
    }
  }, [loadScenarios, loadCurrent, loadSupporting, scenarioId])

  useEffect(() => {
    if (!token) {
      setWorkspaceLoading(false)
      return
    }
    refreshAll()
  // Load the signed-in workspace once per authentication change.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])
  useEffect(() => {
    if (!notice) return
    const id = window.setTimeout(() => setNotice(''), 4200)
    return () => window.clearTimeout(id)
  }, [notice])

  const state = current?.state
  const plan = current?.plan
  const missions = state?.missions || []
  const assignments = plan?.assignments || []
  const assignedIds = useMemo(() => new Set(assignments.map(a => a.mission_id)), [assignments])
  const missionRows = useMemo(() => {
    const byMission = new Map(assignments.map(a => [a.mission_id, a]))
    return missions.map(m => ({ ...m, assignment: byMission.get(m.id), flown: byMission.has(m.id) }))
      .filter(m => `${m.id} ${m.sector} ${m.ac_type} ${m.assignment?.aircraft_id || ''}`.toLowerCase().includes(search.toLowerCase()))
      .filter(m => filterStatus === 'all' || (filterStatus === 'assigned' ? m.flown : !m.flown))
      .sort((a, b) => (a.priority || 5) - (b.priority || 5) || a.earliest - b.earliest)
  }, [missions, assignments, search, filterStatus])
  const currentStats = useMemo(() => {
    const total = missions.length
    const flown = assignments.length
    const ready = (state?.aircraft || []).filter(a => !a.outages?.length && (a.p_serviceable ?? 1) >= 0.7).length
    const sectors = Object.keys(state?.weather || {}).length
    return { total, flown, pending: Math.max(0, total - flown), ready, aircraft: state?.aircraft?.length || 0, crew: state?.crew?.length || 0, sectors }
  }, [state, missions, assignments])
  const isPlanner = ['planner', 'approver'].includes(role)
  const isApprover = role === 'approver'

  async function login(e) {
    e.preventDefault(); setLoginBusy(true); setLoginError('')
    try {
      const data = await request('/api/auth/login', '', { method: 'POST', body: JSON.stringify(loginForm) })
      sessionStorage.setItem('veer_token', data.access_token); sessionStorage.setItem('veer_role', data.role); sessionStorage.setItem('veer_user', loginForm.username)
      setWorkspaceLoading(true); setToken(data.access_token); setRole(data.role); setUsername(loginForm.username); setNotice(`Signed in as ${loginForm.username}`)
    } catch (e) { setLoginError(e.message) } finally { setLoginBusy(false) }
  }
  function logout() {
    sessionStorage.removeItem('veer_token'); sessionStorage.removeItem('veer_role'); sessionStorage.removeItem('veer_user')
    setToken(''); setRole(''); setUsername(''); setCurrent(null); setScenarios([]); setScenarioId(''); setProvenance(null); setHistory([]); setEvaluation(null); setWorkspaceLoading(false); setError(''); setNotice('')
  }
  async function createScenario(e) {
    e.preventDefault(); setBusy(true); setWorkspaceLoading(true); setError('')
    try {
      const created = await call('/api/scenarios', { method: 'POST', body: JSON.stringify({ ...createForm, seed: Number(createForm.seed), trap_groups: Number(createForm.trap_groups), tightness: Number(createForm.tightness) }) })
      setShowCreate(false); await loadScenarios(created.id); await loadCurrent(created.id); await loadSupporting(created.id); setNotice('Scenario created. Generate a plan to populate the mission board.')
    } catch (e) { setError(e.message) } finally { setBusy(false); setWorkspaceLoading(false) }
  }
  async function pollJob(jobId, label) {
    setJob({ id: jobId, status: 'QUEUED', label })
    const started = Date.now()
    while (Date.now() - started < 15 * 60 * 1000) {
      await new Promise(r => window.setTimeout(r, 1200))
      const status = await call(`/api/jobs/${jobId}`)
      setJob({ id: jobId, type: status.type, status: status.status, label, error: status.error })
      if (['COMPLETED', 'FAILED', 'CANCELLED', 'ABANDONED'].includes(status.status)) {
        if (status.status === 'COMPLETED') {
          setNotice(`${label} completed successfully`)
          if (status.type === 'replan_options') { setReplanResult(status.result); setSelectedOption(status.result?.options?.[0]?.label || '') }
          else { await loadCurrent(scenarioId); await loadSupporting(scenarioId) }
        } else setError(status.error || `${label} ${status.status.toLowerCase()}`)
        return status
      }
    }
    throw new Error('This task is taking longer than expected. You can refresh the job status later.')
  }
  async function generatePlan() {
    if (!scenarioId) return
    setBusy(true); setError(''); setReplanResult(null)
    try {
      const r = await call(`/api/scenarios/${scenarioId}/plan`, { method: 'POST', body: JSON.stringify({ time_limit: 10, seed: 7 }) })
      await pollJob(r.job_id, 'Plan generation')
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function suggestDisruption() {
    if (!scenarioId) return
    setBusy(true); setError('')
    try {
      const suggested = await call(`/api/scenarios/${scenarioId}/events/suggest?kind=combined&seed=${Date.now() % 10000}`, { method: 'POST' })
      setEvents(suggested); setManualEvents([]); setImpact(null); setReplanResult(null); setActive('replanning')
      setNotice(`${suggested.length} simulated disruption${suggested.length === 1 ? '' : 's'} added for review`)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  function addManualEvent(e) {
    e.preventDefault()
    if (eventForm.type === 'AIRCRAFT_OUT' && !state?.aircraft?.length) { setError('No aircraft records are available in this scenario.'); return }
    if (eventForm.type === 'CREW_OUT' && !state?.crew?.length) { setError('No crew records are available in this scenario.'); return }
    if (eventForm.type === 'RUNWAY_CLOSED' && !state?.bases?.length) { setError('No base records are available in this scenario.'); return }
    const item = { id: `UI-${Date.now()}`, type: eventForm.type, time: Number(eventForm.time), duration: Number(eventForm.duration), severity: Number(eventForm.severity), payload: {} }
    if (eventForm.type === 'WEATHER' || eventForm.type === 'THREAT_POPUP') item.sector = eventForm.sector
    if (eventForm.type === 'AIRCRAFT_OUT') item.target_id = state.aircraft[0].id
    if (eventForm.type === 'CREW_OUT') item.target_id = state.crew[0].id
    if (eventForm.type === 'RUNWAY_CLOSED') item.target_id = state.bases[0].id
    setManualEvents(prev => [...prev, item]); setShowEventForm(false); setImpact(null); setReplanResult(null)
  }
  const allEvents = [...events, ...manualEvents]
  async function analyseImpact() {
    if (!scenarioId || !allEvents.length) { setError('Add or suggest a disruption first.'); return }
    setBusy(true); setError('')
    try { const result = await call(`/api/scenarios/${scenarioId}/impact`, { method: 'POST', body: JSON.stringify({ events: allEvents }) }); setImpact(result); setNotice('Impact analysis is ready') }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function runReplan() {
    if (!allEvents.length) { setError('Add or suggest a disruption first.'); return }
    setBusy(true); setError('')
    try {
      const r = await call(`/api/scenarios/${scenarioId}/replan`, { method: 'POST', body: JSON.stringify({ events: allEvents, time_limit: 5, seed: 7, robustness_trials: 60 }) })
      await pollJob(r.job_id, 'Alternative plans')
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function decide(action, optionLabel) {
    if (!isApprover) { setError('Only an approver can apply a plan.'); return }
    if (!job?.id || job.type !== 'replan_options' || job.status !== 'COMPLETED') { setError('A completed alternative-plan job is required.'); return }
    setBusy(true); setError('')
    try {
      const result = await call('/api/decisions', { method: 'POST', body: JSON.stringify({ scenario_id: scenarioId, action, job_id: job.id, option_label: optionLabel, reason: decisionReason }) })
      setNotice(action === 'approve' ? `Plan applied as version ${result.version_no}` : 'Option rejected and recorded')
      if (action === 'approve') { setReplanResult(null); setImpact(null); setEvents([]); setManualEvents([]); await loadScenarios(scenarioId); await loadCurrent(scenarioId) }
      await loadSupporting(scenarioId)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function resetScenario() {
    if (!window.confirm('Return this scenario to its original version? This action will be recorded.')) return
    setBusy(true); setError('')
    try { await call(`/api/scenarios/${scenarioId}/reset`, { method: 'POST' }); await loadCurrent(scenarioId); await loadSupporting(scenarioId); setReplanResult(null); setNotice('Scenario returned to its original version') }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function loadReadiness() {
    setBusy(true); setError('')
    try { const p = await call(`/api/provenance?scenario_id=${encodeURIComponent(scenarioId)}`); setProvenance(p); setNotice('Feeds refreshed') }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function loadHistory() {
    setBusy(true); setError('')
    try { setHistory(await call(`/api/decisions/${scenarioId}`)) } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function rollback(versionId) {
    if (!isApprover) { setError('Only an approver can roll back a version.'); return }
    if (!window.confirm('Roll back to this saved version?')) return
    setBusy(true); setError('')
    try { await call('/api/decisions', { method: 'POST', body: JSON.stringify({ scenario_id: scenarioId, action: 'rollback', rollback_version_id: versionId, reason: 'Rollback requested from history' }) }); await loadScenarios(scenarioId); await loadCurrent(scenarioId); await loadSupporting(scenarioId); setNotice('Scenario rolled back') }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  function downloadReport() {
    const data = { scenario: scenarios.find(s => s.id === scenarioId)?.name, version: current?.version_no, generated_at: new Date().toISOString(), simulation_only: true, summary: currentStats, missions: missionRows.map(m => ({ id: m.id, sector: m.sector, priority: m.priority, assigned: m.flown, aircraft: m.assignment?.aircraft_id || null, crew: m.assignment?.crew_id || null, start_slot: m.assignment?.start ?? null })) }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `veer21-summary-v${current?.version_no || 0}.json`; a.click(); URL.revokeObjectURL(url)
    setNotice('Summary report downloaded')
  }

  if (!token && entryView === 'landing') return <LandingPage onOpenWorkspace={() => { setEntryView('login'); window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#workspace`); window.scrollTo({ top: 0, behavior: 'smooth' }) }} />
  if (!token) return <Login form={loginForm} setForm={setLoginForm} onSubmit={login} busy={loginBusy} error={loginError} onBack={() => { setEntryView('landing'); window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`) }} />

  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? 'sidebar-open' : ''}`}>
      <div className="brand"><div className="brand-mark"><img src="/assets/veer-roundel.png" alt="" /></div><div><div className="brand-name">VEER<span>·21</span></div><div className="brand-sub">AIR OPERATIONS</div></div><button className="icon-button sidebar-close" onClick={() => setMobileNav(false)} aria-label="Close menu"><X size={18}/></button></div>
      <div className="workspace-label">WORKSPACE</div>
      <button className="scenario-switch" onClick={() => setShowCreate(true)} disabled={!isPlanner}><div className="scenario-icon"><Layers3 size={17}/></div><div className="scenario-switch-copy"><b>{scenarios.find(s => s.id === scenarioId)?.name || 'Select a scenario'}</b><small>{current ? `Version ${current.version_no} · Simulation` : 'Create a scenario to begin'}</small></div><Plus size={16}/></button>
      <div className="nav-label">COMMAND</div>
      <nav className="nav-list">{NAV.map(item => { const Icon = item.icon; return <button key={item.id} className={`nav-item ${active === item.id ? 'active' : ''}`} onClick={() => { setActive(item.id); setMobileNav(false); if (item.id === 'history') loadHistory() }}><Icon size={18}/><span>{item.label}</span>{item.id === 'replanning' && allEvents.length > 0 && <span className="nav-count">{allEvents.length}</span>}</button> })}</nav>
      <div className="sidebar-bottom"><div className="sim-card"><div className="sim-icon"><ShieldCheck size={18}/></div><div><b>Simulation mode</b><p>Fictional data only. Not connected to live operations.</p></div></div><div className="user-row"><div className="avatar">{(username || 'U').slice(0, 1).toUpperCase()}</div><div className="user-copy"><b>{username || 'User'}</b><small>{pretty(role)} access</small></div><button className="icon-button logout" onClick={logout} title="Sign out"><LogOut size={17}/></button></div></div>
    </aside>
    {mobileNav && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}
    <main className="main-area">
      <header className="topbar"><div className="topbar-left"><button className="icon-button menu-button" onClick={() => setMobileNav(true)} aria-label="Open menu"><Menu size={20}/></button><div className="breadcrumbs"><span>Workspace</span><ChevronRight size={14}/><b>{NAV.find(n => n.id === active)?.label || 'Overview'}</b></div></div><div className="topbar-right"><span className="sim-pill"><span className="live-dot"/> SIMULATED ENVIRONMENT</span><span className={`connection ${health?.status === 'ok' ? 'connected' : ''}`} title={health?.status === 'ok' ? 'API connected' : 'API connection unknown'}><Wifi size={16}/><span>{health?.status === 'ok' ? 'Connected' : 'Checking'}</span></span><button className="icon-button" onClick={() => refreshAll()} title="Refresh dashboard" disabled={workspaceLoading}><RefreshCw size={17}/></button><button className="icon-button notification-button" onClick={() => setActive('replanning')} title="Review disruptions"><Bell size={17}/>{allEvents.length > 0 && <i/>}</button></div></header>
      <div className="page-content">
        {error && (current || workspaceLoading) && <div className="alert alert-error" role="alert"><AlertCircle size={18}/><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss"><X size={16}/></button></div>}
        {notice && <div className="toast" role="status"><CheckCircle2 size={17}/>{notice}<button onClick={() => setNotice('')} aria-label="Dismiss"><X size={15}/></button></div>}
        {workspaceLoading ? <WorkspaceLoading /> : error && !current ? <WorkspaceError message={error} onRefresh={() => refreshAll()} loading={workspaceLoading}/> : !scenarioId || !current ? <EmptyWorkspace isPlanner={isPlanner} onCreate={() => setShowCreate(true)} onRefresh={() => refreshAll()} loading={busy || workspaceLoading}/> : <>
          {active === 'overview' && <Overview isPlanner={isPlanner} state={state} plan={plan} stats={currentStats} scenario={scenarios.find(s => s.id === scenarioId)} current={current} provenance={provenance} busy={busy} job={job} onPlan={generatePlan} onSuggest={suggestDisruption} onOpen={setActive} onDownload={downloadReport} onRefresh={() => refreshAll()} missionRows={missionRows} selectedMission={selectedMission} setSelectedMission={setSelectedMission}/>}
          {active === 'missions' && <MissionBoard isPlanner={isPlanner} rows={missionRows} search={search} setSearch={setSearch} filterStatus={filterStatus} setFilterStatus={setFilterStatus} selectedMission={selectedMission} setSelectedMission={setSelectedMission} state={state} plan={plan} onPlan={generatePlan} busy={busy}/>}
          {active === 'replanning' && <ScenarioLab isPlanner={isPlanner} state={state} plan={plan} events={allEvents} setEvents={setEvents} setManualEvents={setManualEvents} impact={impact} result={replanResult} selectedOption={selectedOption} setSelectedOption={setSelectedOption} busy={busy} job={job} isPlanner={isPlanner} isApprover={isApprover} onSuggest={suggestDisruption} onImpact={analyseImpact} onReplan={runReplan} onAddEvent={() => setShowEventForm(true)} onDecide={decide} reason={decisionReason} setReason={setDecisionReason} onReset={resetScenario} current={current}/>}
          {active === 'readiness' && <Readiness state={state} provenance={provenance} busy={busy} onRefresh={loadReadiness}/>}
          {active === 'history' && <History history={history} versions={scenarioVersions} isApprover={isApprover} busy={busy} onRefresh={loadHistory} onRollback={rollback} current={current}/>}
          {active === 'evaluation' && <Performance evaluation={evaluation} busy={busy} onRefresh={() => loadSupporting(scenarioId)}/>}
        </>}
      </div>
      <footer className="footer"><span>VEER-21 <b>•</b> Decision-support prototype</span><span><ShieldCheck size={13}/> Synthetic data · Human review required</span></footer>
    </main>
    {showCreate && <Modal title="Create a scenario" subtitle="Generate a new synthetic planning environment." onClose={() => setShowCreate(false)}><form className="form-stack" onSubmit={createScenario}><label>Scenario name<input value={createForm.name} onChange={e => setCreateForm({ ...createForm, name: e.target.value })} required maxLength={80}/></label><div className="form-grid"><label>Scenario size<select value={createForm.size} onChange={e => setCreateForm({ ...createForm, size: e.target.value })}><option value="S">Small</option><option value="M">Medium</option><option value="L">Large</option><option value="XL">Extra large</option></select></label><label>Variation seed<input type="number" value={createForm.seed} onChange={e => setCreateForm({ ...createForm, seed: e.target.value })}/></label></div><label>Planning tightness <span className="inline-value">{Number(createForm.tightness).toFixed(2)}</span><input type="range" min="0.5" max="1.2" step="0.05" value={createForm.tightness} onChange={e => setCreateForm({ ...createForm, tightness: e.target.value })}/><small className="field-hint">Controls how constrained the generated scenario is.</small></label><label>Challenge groups<input type="number" min="0" max="20" value={createForm.trap_groups} onChange={e => setCreateForm({ ...createForm, trap_groups: e.target.value })}/></label><div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button><button className="btn btn-primary" disabled={busy}>{busy ? <><span className="spinner"/> Creating…</> : <><Plus size={16}/> Create scenario</>}</button></div></form></Modal>}
    {showEventForm && <Modal title="Add a simulated event" subtitle="Create a scenario change for impact review." onClose={() => setShowEventForm(false)}><form className="form-stack" onSubmit={addManualEvent}><label>Event type<select value={eventForm.type} onChange={e => setEventForm({ ...eventForm, type: e.target.value })}><option value="WEATHER">Weather change</option><option value="THREAT_POPUP">New risk in a sector</option><option value="AIRCRAFT_OUT">Aircraft unavailable</option><option value="CREW_OUT">Crew unavailable</option><option value="RUNWAY_CLOSED">Base runway closure</option></select></label><div className="form-grid"><label>Starts at (15-min slots)<input type="number" min="0" value={eventForm.time} onChange={e => setEventForm({ ...eventForm, time: e.target.value })}/></label><label>Duration (slots)<input type="number" min="1" value={eventForm.duration} onChange={e => setEventForm({ ...eventForm, duration: e.target.value })}/></label></div>{['WEATHER', 'THREAT_POPUP'].includes(eventForm.type) && <div className="form-grid"><label>Sector<select value={eventForm.sector} onChange={e => setEventForm({ ...eventForm, sector: e.target.value })}>{['ALPHA','BRAVO','CHARLIE','DELTA'].map(s => <option key={s}>{s}</option>)}</select></label><label>Severity (0–5)<input type="number" min="0" max="5" value={eventForm.severity} onChange={e => setEventForm({ ...eventForm, severity: e.target.value })}/></label></div>}<p className="field-hint">Aircraft, crew and base events use the first available item of that type in the current scenario.</p><div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={() => setShowEventForm(false)}>Cancel</button><button className="btn btn-primary"><Plus size={16}/> Add event</button></div></form></Modal>}
  </div>
}

function LandingPage({ onOpenWorkspace }) {
  const [apiStatus, setApiStatus] = useState('checking')

  useEffect(() => {
    let active = true
    fetch(`${API_BASE}/health`, { headers: { Accept: 'application/json' } })
      .then(async response => {
        const data = await response.json().catch(() => null)
        if (!response.ok || data?.status === 'offline') throw new Error('API unavailable')
        if (active) setApiStatus(data?.status === 'ok' ? 'connected' : 'degraded')
      })
      .catch(() => { if (active) setApiStatus('offline') })
    return () => { active = false }
  }, [])

  const capabilities = [
    { id: 'overview', title: 'Overview', detail: 'Scenario summary and assignment coverage.', icon: LayoutDashboard },
    { id: 'missions', title: 'Mission board', detail: 'Search missions and inspect assignment details.', icon: Target },
    { id: 'replanning', title: 'Scenario lab', detail: 'Assess disruptions and compare alternative plans.', icon: RefreshCw },
    { id: 'readiness', title: 'Readiness & feeds', detail: 'Inspect feed provenance, freshness and conflicts.', icon: Radio },
    { id: 'history', title: 'Decision history', detail: 'Review saved scenario versions and decisions.', icon: FileClock },
    { id: 'evaluation', title: 'Performance', detail: 'Review returned benchmark and evaluation results.', icon: Gauge },
  ]

  return <main className="public-landing" id="top">
    <header className="public-nav">
      <a className="public-brand" href="#top" aria-label="VEER-21 home">
        <span className="public-brand-mark"><img src="/assets/veer-roundel.png" alt="" /></span>
        <span className="public-brand-type"><strong>VEER<span>·21</span></strong><small>AIR OPERATIONS</small></span>
      </a>
      <nav className="public-nav-links" aria-label="Main navigation">
        <a href="#capabilities">Workspace areas</a>
        <a href="#workflow">Workflow</a>
        <a href="#environment">Environment</a>
      </nav>
      <button className="btn btn-primary public-nav-button" onClick={onOpenWorkspace}>Open workspace <ArrowRight size={16}/></button>
    </header>

    <section className="public-hero public-hero-institutional">
      <div className="public-hero-aircraft" aria-hidden="true"><img src="/assets/aircraft-silhouette.svg" alt="" /></div>
      <div className="public-hero-seal"><img src="/assets/veer-roundel.png" alt="VEER-21 air operations emblem" /></div>
      <div className="public-hero-copy public-hero-copy-centered">
        <div className="public-eyebrow public-eyebrow-centered"><span className="public-eyebrow-line"/> AIR OPERATIONS PLANNING <span className="public-eyebrow-line"/></div>
        <h1>VEER·21<br/><span>Air Operations</span></h1>
        <p className="public-hero-description">Mission assignments, scenario disruptions, alternative-plan review and decision history in one workspace.</p>
        <div className="public-hero-actions public-hero-actions-centered">
          <button className="btn btn-primary public-primary-cta" onClick={onOpenWorkspace}>Open workspace <ArrowRight size={17}/></button>
          <a className="public-text-link" href="#capabilities">Explore workspace areas <ChevronRight size={17}/></a>
        </div>
        <div className={`public-api-status ${apiStatus}`} role="status" aria-live="polite">
          <span className="public-api-indicator">{apiStatus === 'checking' ? <span className="spinner small-spinner"/> : apiStatus === 'connected' ? <CheckCircle2 size={14}/> : <AlertCircle size={14}/>}</span>
          <span className="public-api-message">{apiStatus === 'checking' ? 'Checking workspace API' : apiStatus === 'connected' ? 'Workspace API connected' : apiStatus === 'degraded' ? 'Workspace API reachable · service degraded' : 'Workspace API unavailable'}</span>
          <span className="public-api-divider"/>
          <span>{apiStatus === 'offline' ? 'Landing page remains available' : 'Frontend available'}</span>
        </div>
      </div>
      <a href="#capabilities" className="public-scroll-cue"><span className="public-scroll-line"/> EXPLORE WORKSPACE</a>
    </section>

    <section className="public-capabilities" id="capabilities">
      <div className="public-section-heading"><div><span className="public-eyebrow"><span className="public-eyebrow-line"/> WORKSPACE AREAS</span><h2>One workspace.<br/><span>Six connected views.</span></h2></div><p>Each view maps to an existing VEER·21 workspace area. Operational results load from the connected API when available.</p></div>
      <div className="public-capability-grid">
        {capabilities.map((item, index) => { const Icon = item.icon; return <article className="public-capability-card" key={item.id}><div className="public-capability-card-top"><span className="public-capability-index">0{index + 1}</span><span className="public-capability-icon"><Icon size={19}/></span></div><h3>{item.title}</h3><p>{item.detail}</p><button onClick={onOpenWorkspace} className="public-capability-open" aria-label={`Open workspace to access ${item.title}`}>Open workspace <ArrowRight size={15}/></button></article> })}
      </div>
    </section>

    <section className="public-workflow" id="workflow">
      <div className="public-workflow-intro"><span className="public-eyebrow"><span className="public-eyebrow-line"/> WORKFLOW</span><h2>Plan, evaluate,<br/>review and decide.</h2><p>Actions that change scenario state are handled by the API and require the appropriate role.</p><button className="btn btn-primary" onClick={onOpenWorkspace}>Enter workspace <ArrowRight size={16}/></button></div>
      <div className="public-workflow-steps">
        <article><span className="public-step-number">01</span><div><h3>Review the mission board</h3><p>Search missions and inspect assignment details in the selected scenario.</p></div><Target size={19}/></article>
        <article><span className="public-step-number">02</span><div><h3>Assess scenario changes</h3><p>Review a disruption's impact and compare alternative plans returned by the engine.</p></div><RefreshCw size={19}/></article>
        <article><span className="public-step-number">03</span><div><h3>Review saved decisions</h3><p>Inspect scenario versions and decision history with role-based controls.</p></div><FileClock size={19}/></article>
      </div>
    </section>

    <section className="public-environment" id="environment"><span className="public-environment-icon"><ShieldCheck size={21}/></span><div><strong>Simulation environment</strong><p>Uses synthetic scenario data and illustrative routes. Not connected to live operational feeds.</p></div><button className="btn btn-secondary" onClick={onOpenWorkspace}>Open workspace <ArrowRight size={16}/></button></section>
    <footer className="public-footer"><a className="public-brand" href="#top"><span className="public-brand-mark"><img src="/assets/veer-roundel.png" alt="" /></span><span className="public-brand-type"><strong>VEER<span>·21</span></strong><small>AIR OPERATIONS</small></span></a><span>Decision-support prototype</span><a href="#top" className="public-back-top">Back to top ↑</a></footer>
  </main>
}

function Login({ form, setForm, onSubmit, busy, error, onBack }) {
  const [showPassword, setShowPassword] = useState(false)
  const [apiStatus, setApiStatus] = useState('checking')

  useEffect(() => {
    let active = true
    fetch(`${API_BASE}/health`, { headers: { Accept: 'application/json' } })
      .then(async response => {
        const data = await response.json().catch(() => null)
        if (!response.ok || data?.status === 'offline') throw new Error('API unavailable')
        if (active) setApiStatus(data?.status === 'ok' ? 'connected' : 'available')
      })
      .catch(() => { if (active) setApiStatus('offline') })
    return () => { active = false }
  }, [])

  const apiLabel = apiStatus === 'checking' ? 'Checking API connection' : apiStatus === 'connected' || apiStatus === 'available' ? 'API reachable' : 'API unavailable'
  return <main className="login-page">
    <section className="login-art" aria-label="VEER-21 product overview">
      <div className="login-grid" aria-hidden="true" />
      <div className="login-glow login-glow-one" aria-hidden="true" />
      <div className="login-glow login-glow-two" aria-hidden="true" />
      <div className="login-brand"><div className="brand-mark"><img src="/assets/veer-roundel.png" alt="" /></div><div><div className="brand-name">VEER<span>·21</span></div><div className="brand-sub">AIR OPERATIONS</div></div></div>
      <div className="login-art-copy">
        <span className="eyebrow light"><span className="live-dot"/> DECISION SUPPORT PROTOTYPE</span>
        <h1>Air<br/><span className="hero-product-dot">Operations</span></h1>
        <div className="login-capabilities">
          {NAV.map(item => { const Icon = item.icon; return <div className="login-capability" key={item.id}><span><Icon size={16}/></span><b>{item.label}</b></div> })}
        </div>
      </div>
      <div className="login-art-foot"><ShieldCheck size={15}/> Fictional data only. Not connected to live operations.</div>
    </section>
    <section className="login-panel">
      <div className="login-panel-inner">
        <div className="login-mobile-brand"><div className="brand-mark"><img src="/assets/veer-roundel.png" alt="" /></div><div><div className="brand-name">VEER<span>·21</span></div><div className="brand-sub">AIR OPERATIONS</div></div></div>
        <button type="button" className="login-back" onClick={onBack}><ChevronLeft size={15}/> Back to landing page</button>
        <span className="eyebrow">ACCOUNT ACCESS</span>
        <h2>Sign in</h2>
        <p className="muted login-desc">Use an account created by your project administrator.</p>
        {error && <div className="alert alert-error" role="alert"><AlertCircle size={17}/><span>{error}</span></div>}
        <form className="form-stack login-form" onSubmit={onSubmit}>
          <label htmlFor="login-username">Username<input id="login-username" autoComplete="username" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} placeholder="Enter your username" required/></label>
          <label htmlFor="login-password">Password
            <span className="password-field"><input id="login-password" autoComplete="current-password" type={showPassword ? 'text' : 'password'} value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} placeholder="Enter your password" required/><button className="password-toggle" type="button" onClick={() => setShowPassword(value => !value)} aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword}>{showPassword ? <EyeOff size={17}/> : <Eye size={17}/>}</button></span>
          </label>
          <button className="btn btn-primary btn-full login-submit" disabled={busy}>{busy ? <><span className="spinner"/> Signing in…</> : <>Sign in <ArrowRight size={17}/></>}</button>
        </form>
        <div className="login-note"><ShieldCheck size={17}/><span>Your role determines which review actions are available.</span></div>
        <div className={`login-api api-${apiStatus}`} aria-live="polite"><span className="api-indicator">{apiStatus === 'checking' ? <span className="spinner small-spinner"/> : apiStatus === 'connected' || apiStatus === 'available' ? <CheckCircle2 size={14}/> : <AlertCircle size={14}/>}</span><div><b>{apiLabel}</b><code>{API_BASE}</code></div></div>
      </div>
    </section>
  </main>
}

function WorkspaceLoading() {
  return <div className="workspace-loading" role="status" aria-label="Loading workspace">
    <div className="loading-heading"><span className="skeleton-line skeleton-eyebrow"/><span className="skeleton-line skeleton-title"/><span className="skeleton-line skeleton-description"/></div>
    <div className="loading-stats">{[0, 1, 2, 3].map(item => <div className="loading-card" key={item}><span className="skeleton-line skeleton-label"/><span className="skeleton-line skeleton-value"/><span className="skeleton-line skeleton-caption"/></div>)}</div>
    <div className="loading-columns"><div className="loading-panel"><span className="skeleton-line skeleton-panel-title"/><div className="skeleton-map"/><span className="skeleton-line skeleton-caption"/></div><div className="loading-panel"><span className="skeleton-line skeleton-panel-title"/>{[0, 1, 2, 3, 4].map(item => <span className="skeleton-line skeleton-row" key={item}/>)}</div></div>
  </div>
}

function WorkspaceError({ message, onRefresh, loading }) {
  return <div className="workspace-error"><Wifi size={27}/><h2>Workspace unavailable</h2><p>{message}</p><Button icon={RefreshCw} variant="primary" onClick={onRefresh} disabled={loading}>{loading ? 'Refreshing…' : 'Retry'}</Button></div>
}

function PageHeading({ eyebrow, title, description, actions }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{actions && <div className="heading-actions">{actions}</div>}</div>
}
function Button({ children, variant = 'secondary', onClick, disabled, icon: Icon, className = '', type = 'button' }) {
  return <button type={type} className={`btn btn-${variant} ${className}`} onClick={onClick} disabled={disabled}>{Icon && <Icon size={16}/>}{children}</button>
}
function EmptyWorkspace({ isPlanner, onCreate, onRefresh, loading }) {
  return <div className="empty-workspace"><div className="empty-illustration"><div className="empty-ring ring-one"/><div className="empty-ring ring-two"/><div className="empty-plane"><Plane size={37}/></div></div><div className="eyebrow">YOUR WORKSPACE IS READY</div><h1>Start with a scenario</h1><p>Create a fictional planning scenario to explore the mission board, simulated conditions, and alternative-plan review.</p><div className="empty-actions"><Button variant="primary" icon={Plus} onClick={onCreate} disabled={!isPlanner}>Create scenario</Button><Button icon={RefreshCw} onClick={onRefresh} disabled={loading}>Refresh list</Button></div><small>{isPlanner ? 'Existing scenarios will appear in the left sidebar after refresh.' : 'No scenarios are available. Ask a planner to create one or grant access to an existing scenario.'}</small></div>
}

function Overview({ isPlanner, state, plan, stats, scenario, current, provenance, busy, job, onPlan, onSuggest, onOpen, onDownload, onRefresh, missionRows, selectedMission, setSelectedMission }) {
  const hasPlan = !!plan
  const value = plan?.value ?? 0
  const assigned = plan?.assignments?.length || 0
  const dropped = plan?.dropped?.length || 0
  return <>
    <PageHeading eyebrow="OPERATIONS SNAPSHOT" title="Overview" description="Scenario readiness, planned activity, and the latest conditions." actions={<><Button icon={Download} onClick={onDownload}>Export summary</Button><Button variant="primary" icon={Plus} onClick={onSuggest} disabled={!hasPlan || busy || !isPlanner}>Simulate disruption</Button></>}/>
    <div className="context-strip"><div className="context-left"><div className="context-icon"><Layers3 size={18}/></div><div><b>{scenario?.name || 'Current scenario'}</b><span>{`Version ${current.version_no} · ${state?.missions?.length || 0} missions in this scenario`}</span></div></div><div className="context-right"><span className="version-tag"><span className="live-dot"/> SIMULATION</span><Button icon={RefreshCw} onClick={onRefresh}>Refresh</Button></div></div>
    <div className="stat-grid"><StatCard label="Missions planned" value={`${assigned} / ${stats.total}`} detail={hasPlan ? `${Math.round(assigned / Math.max(stats.total, 1) * 100)}% currently assigned` : 'Generate a plan to begin'} icon={Target} tone="blue"/><StatCard label="Aircraft in scenario" value={stats.aircraft} detail={`${stats.ready} marked serviceable in sample`} icon={Plane} tone="teal"/><StatCard label="Crew records" value={fmt(stats.crew)} detail="Across all assigned bases" icon={Users} tone="purple"/><StatCard label="Plan value" value={hasPlan ? fmt(value) : '—'} detail={hasPlan ? `${dropped} missions not assigned` : 'Available after planning'} icon={Gauge} tone="amber"/></div>
    <div className="overview-grid"><section className="panel map-panel"><div className="panel-heading"><div><h3>Operational picture</h3><p>Fictional sectors · illustrative positions, not live tracking</p></div><button className="text-button" onClick={() => onOpen('missions')}>Mission board <ArrowRight size={15}/></button></div><OperationalMap state={state} assignments={plan?.assignments || []} selectedMission={selectedMission} onSelectMission={setSelectedMission}/><div className="map-footer"><span><i className="legend-dot blue"/> Assigned</span><span><i className="legend-dot teal"/> Base</span><span><i className="legend-dot amber"/> Needs review</span><span><i className="legend-line"/> Illustrative route</span></div></section><section className="panel activity-panel"><div className="panel-heading"><div><h3>Planning status</h3><p>At-a-glance workflow progress</p></div><span className={`status-chip ${hasPlan ? 'success' : 'neutral'}`}>{hasPlan ? 'Plan available' : 'Not planned'}</span></div><div className="progress-block"><div className="progress-label"><span>Mission coverage</span><b>{hasPlan ? Math.round(assigned / Math.max(stats.total, 1) * 100) : 0}%</b></div><div className="progress-track"><div className="progress-fill" style={{ width: `${hasPlan ? assigned / Math.max(stats.total, 1) * 100 : 0}%` }}/></div><div className="progress-caption"><span>{assigned} assigned</span><span>{stats.pending} remaining</span></div></div><div className="activity-list"><ActivityRow icon={Database} tone="blue" title="Scenario information" text={`${stats.sectors} sectors represented in the current sample`} status="Available"/><ActivityRow icon={Cloud} tone="teal" title="Conditions & feeds" text={provenance ? `${provenance.readings?.length || provenance.records?.length || 'Multiple'} readings returned` : 'Refresh to view feed status'} status={provenance ? 'Checked' : 'Pending'}/><ActivityRow icon={ShieldCheck} tone={hasPlan && !(plan?.violations?.length) ? 'teal' : 'amber'} title="Plan checks" text={hasPlan ? `${plan.violations?.length || 0} reported issues` : 'No plan has been generated'} status={hasPlan ? (plan.violations?.length ? 'Review' : 'Clear') : 'Waiting'}/></div>{!hasPlan ? <Button variant="primary" icon={Sparkles} className="btn-full" onClick={onPlan} disabled={busy}>{busy ? 'Working…' : 'Generate initial plan'}</Button> : <Button icon={RefreshCw} className="btn-full" onClick={() => onOpen('replanning')}>Open scenario lab</Button>}{job && <div className={`job-line ${job.status === 'FAILED' || job.status === 'CANCELLED' || job.status === 'ABANDONED' ? 'job-line-error' : job.status === 'COMPLETED' ? 'job-line-done' : ''}`}><span className={job.status === 'COMPLETED' ? 'job-state-icon' : job.status === 'FAILED' || job.status === 'CANCELLED' || job.status === 'ABANDONED' ? 'job-state-icon' : 'spinner small-spinner'}>{job.status === 'COMPLETED' ? '✓' : ['FAILED','CANCELLED','ABANDONED'].includes(job.status) ? '!' : ''}</span>{job.label}: {pretty(job.status)}</div>}</section></div>
    <section className="panel missions-preview"><div className="panel-heading"><div><h3>Mission overview</h3><p>Highest-priority activity in the current scenario</p></div><button className="text-button" onClick={() => onOpen('missions')}>View all missions <ArrowRight size={15}/></button></div><MissionTable rows={missionRows.slice(0, 5)} selectedMission={selectedMission} setSelectedMission={setSelectedMission} compact/></section>
    <div className="disclaimer"><ShieldCheck size={16}/><span>This prototype uses synthetic scenario data. Map positions and routes are illustrative and do not represent real aircraft, locations, or live operational feeds.</span></div>
  </>
}
function StatCard({ label, value, detail, icon: Icon, tone }) { return <div className="stat-card"><div className={`stat-icon ${tone}`}><Icon size={19}/></div><div className="stat-label">{label}</div><div className="stat-value">{value}</div><div className="stat-detail">{detail}</div></div> }
function ActivityRow({ icon: Icon, tone, title, text, status }) { return <div className="activity-row"><div className={`activity-icon ${tone}`}><Icon size={16}/></div><div className="activity-copy"><b>{title}</b><span>{text}</span></div><span className={`mini-status ${status === 'Clear' || status === 'Checked' || status === 'Available' ? 'good' : status === 'Review' ? 'warn' : ''}`}>{status}</span></div> }

function OperationalMap({ state, assignments, selectedMission, onSelectMission }) {
  const [playing, setPlaying] = useState(true)
  const [time, setTime] = useState(24)
  const [speed, setSpeed] = useState(2)
  useEffect(() => {
    if (!playing) return
    const timer = setInterval(() => setTime(t => (t >= 100 ? 0 : t + speed * 0.22)), 700)
    return () => clearInterval(timer)
  }, [playing, speed])
  const sectorNames = ['ALPHA', 'BRAVO', 'CHARLIE', 'DELTA']
  const sectorPositions = { ALPHA: [190, 108], BRAVO: [430, 100], CHARLIE: [275, 258], DELTA: [500, 255] }
  const bases = (state?.bases || []).slice(0, 5)
  const activeAssignments = assignments.slice(0, 12)
  const missions = new Map((state?.missions || []).map(m => [m.id, m]))
  const palette = ['#2776d2', '#159c9a', '#e6a23c', '#5b7cda', '#20a5b7']
  const minute = Math.round(time * 1.44)
  return <div className="map-canvas animated-map">
    <div className="map-top-label"><span><Compass size={14}/> INDIA OPERATIONS VIEW</span><span className="map-live"><i/> SIMULATED PLAYBACK</span></div>
    <div className="india-map-stage">
      <div className="map-map-grid"/>
      <div className="map-region-tag tag-west">WESTERN REGION</div><div className="map-region-tag tag-east">EASTERN REGION</div>
      <svg className="ops-map india-svg" viewBox="0 0 660 390" role="img" aria-label="Illustrative map of India with simulated aircraft positions and mission routes">
        <defs>
          <linearGradient id="indiaSea" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#f5fbff"/><stop offset="1" stopColor="#e5f4f7"/></linearGradient>
          <linearGradient id="indiaLand" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#e5f1e9"/><stop offset="1" stopColor="#cfe5de"/></linearGradient>
          <pattern id="indiaGrid" width="26" height="26" patternUnits="userSpaceOnUse"><path d="M26 0H0V26" fill="none" stroke="#d5e7ed" strokeWidth=".7"/></pattern>
          <filter id="planeGlow"><feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
        </defs>
        <rect width="660" height="390" fill="url(#indiaSea)"/><rect width="660" height="390" fill="url(#indiaGrid)"/>
        <path d="M185 12 L227 22 255 48 286 58 302 82 335 88 348 112 374 118 386 141 418 149 438 177 457 195 471 217 454 239 431 252 412 277 390 295 374 321 360 346 343 373 327 350 312 325 299 303 279 282 265 258 250 234 235 213 220 194 204 173 190 154 175 134 163 111 157 88 163 65 172 42Z" fill="url(#indiaLand)" stroke="#a6cbc2" strokeWidth="2" transform="translate(20 0)"/>
        <path d="M175 15 L215 26 242 49 275 58 292 82 324 88 338 112 364 118 376 141 408 149 428 177 447 195 461 217 444 239 421 252 402 277 380 295 364 321 350 346 333 373 317 350 302 325 289 303 269 282 255 258 240 234 225 213 210 194 194 173 180 154 165 134 153 111 147 88 153 65 162 42Z" fill="url(#indiaLand)" stroke="#9fc8bd" strokeWidth="1.5"/>
        <path d="M173 30 Q245 80 295 118 T380 205 T330 350" fill="none" stroke="#b6d6cb" strokeWidth="1.4" strokeDasharray="4 5"/>
        <path d="M155 80 Q250 130 325 155 T440 230" fill="none" stroke="#b6d6cb" strokeWidth="1.2" strokeDasharray="3 6"/>
        <path d="M200 20 L205 5 220 0 230 9 219 20" fill="#e7f1e8" stroke="#a6cbc2"/>
        <g fill="#7795a1" fontSize="9" fontWeight="700" letterSpacing="1"><text x="85" y="94">ARABIAN SEA</text><text x="470" y="130">BAY OF BENGAL</text></g>
        <g fill="#6f8994" fontSize="9" fontWeight="700"><text x="235" y="82">CENTRAL INDIA</text><text x="350" y="215">EASTERN REGION</text><text x="177" y="210">WESTERN REGION</text><text x="285" y="364">SOUTHERN REGION</text></g>
        {sectorNames.map((s,i)=>{const [x,y]=sectorPositions[s];const weather=Math.max(...(state?.weather?.[s]||[0]));return <g key={s}><ellipse cx={x} cy={y} rx="70" ry="45" fill={weather>=4?'#fff0d8':'#d9eef0'} opacity=".58" stroke={weather>=4?'#e6b66f':'#a8d5d9'} strokeDasharray="4 5"/><text x={x} y={y-28} textAnchor="middle" fontSize="8" fontWeight="800" letterSpacing="1" fill="#678693">{s}</text>{weather>=4&&<circle cx={x+48} cy={y-28} r="7" fill="#f3bd62"/>}</g>})}
        {activeAssignments.map((a,i)=>{const m=missions.get(a.mission_id);if(!m)return null;const [sx,sy]=sectorPositions[m.sector]||[330,180];const bx=115+((i*73)%420),by=45+((i*47)%300);const x=sx+((i%4)-1.5)*18+Math.sin((time/100)*Math.PI*2+i)*12;const y=sy+((i%3)-1)*15+Math.cos((time/100)*Math.PI*2+i)*8;const active=selectedMission===m.id;const progress=((time/100)+(i*.13))%1;const px=bx+(x-bx)*progress,py=by+(y-by)*progress;return <g key={a.mission_id} className="map-mission" onClick={()=>onSelectMission(active?null:m.id)} role="button" tabIndex="0" aria-label={`Select mission ${m.id}`} onKeyDown={e=>e.key==='Enter'&&onSelectMission(m.id)}><path d={`M${bx} ${by} Q${(bx+x)/2+((i%2)*15)} ${(by+y)/2-15} ${x} ${y}`} fill="none" stroke={active?'#e6a23c':palette[i%palette.length]} strokeWidth={active?2.5:1.3} strokeDasharray="5 5" opacity=".65"/><circle cx={x} cy={y} r={active?9:5.5} fill={active?'#f3b74e':palette[i%palette.length]} stroke="white" strokeWidth="2"/><g transform={`translate(${px} ${py}) rotate(${(i*31+time*1.4)%360})`} filter="url(#planeGlow)"><path d="M0 -8 L2.2 -1 L7 2 L7 4 L2 3 L1 8 L-1 8 L-2 3 L-7 4 L-7 2 L-2.2 -1Z" fill={palette[i%palette.length]} stroke="white" strokeWidth=".8"/></g><text x={x+9} y={y-8} fontSize="8" fontWeight="800" fill="#355b70">{m.id}</text></g>})}
        {bases.map((b,i)=>{const x=145+(i*103)%390,y=315-(i%2)*23;return <g key={b.id}><rect x={x-6} y={y-6} width="12" height="12" rx="3" fill="#129b98" stroke="white" strokeWidth="2"/><text x={x} y={y+17} textAnchor="middle" fontSize="8" fontWeight="800" fill="#147e83">{b.id}</text></g>})}
      </svg>
      <div className="map-scale"><span/> India schematic · not for navigation</div>
    </div>
    <div className="playback-panel">
      <div className="playback-controls"><button className="play-toggle" onClick={()=>setPlaying(v=>!v)} aria-label={playing?'Pause playback':'Start playback'}>{playing?'Ⅱ':'▶'}</button><div className="play-time"><b>{String(Math.floor(minute/60)).padStart(2,'0')}:{String(minute%60).padStart(2,'0')}</b><small>SIMULATION TIME</small></div><div className="timeline-wrap"><input aria-label="Simulation timeline" type="range" min="0" max="100" value={time} onChange={e=>setTime(Number(e.target.value))}/><div className="timeline-ticks"><span>Start</span><span>+36 min</span><span>+72 min</span><span>+108 min</span><span>End</span></div></div><div className="speed-control"><label htmlFor="map-speed">SPEED</label><select id="map-speed" value={speed} onChange={e=>setSpeed(Number(e.target.value))}><option value="0.5">0.5×</option><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option><option value="8">8×</option></select></div></div>
      <div className="playback-foot"><span><i className="legend-dot blue"/> Aircraft in motion</span><span><i className="legend-dot teal"/> Base</span><span><i className="legend-line"/> Mission route</span><span className="playback-hint"><Activity size={12}/> Drag timeline to inspect any point</span></div>
    </div>
  </div>
}

function MissionBoard({ isPlanner, rows, search, setSearch, filterStatus, setFilterStatus, selectedMission, setSelectedMission, state, plan, onPlan, busy }) {
  const selected = rows.find(m => m.id === selectedMission) || (state?.missions || []).find(m => m.id === selectedMission)
  return <><PageHeading eyebrow="MISSION MANAGEMENT" title="Mission board" description="Browse the scenario's mission list and review assignment status in plain language." actions={<Button variant="primary" icon={Sparkles} onClick={onPlan} disabled={busy || !isPlanner}>{plan ? 'Refresh plan' : 'Generate plan'}</Button>}/><div className="stat-grid compact-stats"><StatCard label="Total missions" value={state?.missions?.length || 0} detail="In this scenario" icon={Target} tone="blue"/><StatCard label="Assigned" value={plan?.assignments?.length || 0} detail="Currently in the plan" icon={CheckCircle2} tone="teal"/><StatCard label="Awaiting assignment" value={plan ? (plan.dropped?.length || 0) : (state?.missions?.length || 0)} detail="Review after planning" icon={Clock3} tone="amber"/></div><div className="panel table-panel"><div className="table-toolbar"><div className="search-box"><Search size={17}/><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search mission, sector, aircraft…"/></div><div className="filter-control"><SlidersHorizontal size={16}/><select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}><option value="all">All missions</option><option value="assigned">Assigned</option><option value="pending">Awaiting assignment</option></select></div><span className="result-count">{rows.length} results</span></div><MissionTable rows={rows} selectedMission={selectedMission} setSelectedMission={setSelectedMission}/></div>{selected && <div className="panel selected-detail"><div className="selected-detail-head"><div><span className="eyebrow">SELECTED MISSION</span><h3>{selected.id}</h3></div><button className="icon-button" onClick={() => setSelectedMission(null)} aria-label="Close details"><X size={17}/></button></div><div className="detail-grid"><Detail label="Sector" value={selected.sector}/><Detail label="Priority" value={`Priority ${selected.priority}`}/><Detail label="Mission type" value={friendlyType(selected.ac_type)}/><Detail label="Window opens" value={slots(selected.earliest)}/><Detail label="Window closes" value={slots(selected.latest)}/><Detail label="Duration" value={slots(selected.duration_slots)}/><Detail label="Distance" value={`${fmt(selected.distance_km)} km`}/><Detail label="Assignment" value={selected.assignment ? selected.assignment.aircraft_id : 'Awaiting assignment'}/><Detail label="Crew" value={selected.assignment?.crew_id || 'Not assigned'}/></div></div>}</>
}
function MissionTable({ rows, selectedMission, setSelectedMission, compact = false }) {
  if (!rows?.length) return <div className="table-empty"><Search size={22}/><b>No missions match</b><span>Try changing the search or filter.</span></div>
  return <div className="table-scroll"><table className="data-table"><thead><tr><th>Mission</th><th>Sector</th><th>Priority</th><th>Mission type</th><th>Start window</th><th>Assigned resource</th><th>Status</th>{!compact && <th/>}</tr></thead><tbody>{rows.map(m => <tr key={m.id} className={selectedMission === m.id ? 'row-selected' : ''} onClick={() => setSelectedMission(selectedMission === m.id ? null : m.id)}><td><b className="mission-id">{m.id}</b><small>{slots(m.duration_slots)} duration</small></td><td><span className="sector-tag">{m.sector}</span></td><td><PriorityTag priority={m.priority}/></td><td>{friendlyType(m.ac_type)}</td><td>{slots(m.earliest)} – {slots(m.latest)}</td><td>{m.assignment ? <div className="resource-cell"><Plane size={14}/><span>{m.assignment.aircraft_id}<small>{m.assignment.crew_id}</small></span></div> : <span className="muted">—</span>}</td><td><span className={`status-chip ${m.flown ? 'success' : 'warning'}`}><i/> {m.flown ? 'Assigned' : 'Pending'}</span></td>{!compact && <td><ChevronRight size={16} className="row-chevron"/></td>}</tr>)}</tbody></table></div>
}
function PriorityTag({ priority }) { return <span className={`priority-tag p${priority}`}>P{priority}</span> }
function Detail({ label, value }) { return <div className="detail-item"><span>{label}</span><b>{value}</b></div> }

function ScenarioLab({ state, plan, events, setEvents, setManualEvents, impact, result, selectedOption, setSelectedOption, busy, job, isPlanner, isApprover, onSuggest, onImpact, onReplan, onAddEvent, onDecide, reason, setReason, onReset, current }) {
  const metrics = result?.options?.find(o => o.label === selectedOption)?.metrics
  return <><PageHeading eyebrow="WHAT-IF WORKSPACE" title="Scenario lab" description="Introduce a simulated change, see what it affects, and compare alternatives before any plan is applied." actions={<Button icon={RotateCcw} onClick={onReset} disabled={busy || !isPlanner}>Reset scenario</Button>}/><div className="lab-banner"><div className="lab-banner-icon"><Sparkles size={20}/></div><div><b>Explore a change before committing</b><p>Disruptions stay in review until an authorized approver applies a completed alternative.</p></div><span className="status-chip neutral">Version {current?.version_no}</span></div><div className="lab-layout"><div className="lab-main"><section className="panel"><div className="panel-heading"><div><h3>1. Add a scenario change</h3><p>Use a suggested example or add an event manually.</p></div><span className="step-number">01</span></div><div className="event-actions"><Button variant="primary" icon={Zap} onClick={onSuggest} disabled={busy || !plan || !isPlanner}>Suggest sample disruption</Button><Button icon={Plus} onClick={onAddEvent} disabled={busy}>Add event</Button><span className="field-hint">Uses the current scenario's available plan.</span></div>{events.length ? <div className="event-list">{events.map((ev,i) => <div className="event-row" key={`${ev.id}-${i}`}><div className={`event-icon ${ev.type === 'WEATHER' ? 'amber' : ev.type.includes('OUT') ? 'rose' : 'blue'}`}>{ev.type === 'WEATHER' ? <Cloud size={17}/> : ev.type.includes('OUT') ? <AlertTriangle size={17}/> : <Activity size={17}/>}</div><div className="event-copy"><b>{eventTitle(ev)}</b><span>{eventDescription(ev)} · starts at {slots(ev.time)}</span></div><button className="icon-button remove-event" onClick={() => { const removeId = events[i]?.id; setEvents(prev => prev.filter(ev => ev.id !== removeId)); setManualEvents(prev => prev.filter(ev => ev.id !== removeId)) }} title="Remove event"><X size={16}/></button></div>)}</div> : <div className="event-empty"><div className="event-empty-icon"><Radio size={20}/></div><div><b>No changes added yet</b><span>Suggest a sample disruption to start the review.</span></div></div>}<div className="modal-actions left-actions"><Button icon={Activity} onClick={onImpact} disabled={busy || !events.length}>Assess impact</Button><Button variant="primary" icon={RefreshCw} onClick={onReplan} disabled={busy || !events.length || !isPlanner || !plan}>Compare alternative plans</Button></div>{job && <div className={`job-progress ${job.status === 'COMPLETED' ? 'job-progress-done' : ['FAILED','CANCELLED','ABANDONED'].includes(job.status) ? 'job-progress-error' : ''}`}><div className="job-progress-top"><span>{job.status === 'COMPLETED' ? <CheckCircle2 size={15}/> : ['FAILED','CANCELLED','ABANDONED'].includes(job.status) ? <AlertCircle size={15}/> : <span className="spinner small-spinner"/>} {job.label}</span><b>{pretty(job.status)}</b></div><div className="progress-track"><div className={`progress-fill ${['FAILED','CANCELLED','ABANDONED'].includes(job.status) ? 'fill-error' : ''}`} style={{ width: job.status === 'COMPLETED' || ['FAILED','CANCELLED','ABANDONED'].includes(job.status) ? '100%' : job.status === 'QUEUED' ? '10%' : '58%' }}/></div><small>{job.status === 'COMPLETED' ? 'Results are ready. You can continue to the next step.' : ['FAILED','CANCELLED','ABANDONED'].includes(job.status) ? (job.error || 'This task did not complete. Review the error above and try again.') : 'Processing in the background. This indicator will stop when the task finishes.'}</small></div>}</section>
    {impact && <section className="panel impact-panel"><div className="panel-heading"><div><h3>2. Impact summary</h3><p>What the selected change could affect in this scenario.</p></div><span className="status-chip warning">Review needed</span></div><div className="impact-stats"><div><span>Directly affected</span><b>{impact.impact?.directly_affected?.length || 0}</b></div><div><span>Possible ripple effects</span><b>{impact.impact?.ripple?.length || 0}</b></div><div><span>Value at risk</span><b>{fmt(impact.impact?.value_at_risk)}</b></div></div>{impact.impact?.violations?.length > 0 && <div className="impact-issues">{impact.impact.violations.slice(0,5).map((v,i) => <div key={i}><AlertTriangle size={15}/><span><b>{v.mission_id || 'Scenario'}</b> · {pretty(v.kind)}<small>{v.detail}</small></span></div>)}</div>}{impact.impact?.violations?.length === 0 && <div className="success-note"><CheckCircle2 size={17}/> No constraint issues were reported in this impact assessment.</div>}</section>}
    {result && <section className="panel alternatives-panel"><div className="panel-heading"><div><h3>3. Compare alternatives</h3><p>Review trade-offs; each option is a proposal, not an applied plan.</p></div><span className="status-chip success">{result.options?.length || 0} options ready</span></div><div className="option-grid">{(result.options || []).map((o,i) => { const m=o.metrics||{}; const chosen=selectedOption===o.label; return <button className={`option-card ${chosen ? 'option-selected' : ''}`} key={o.label} onClick={() => setSelectedOption(o.label)}><div className="option-top"><span className={`option-letter letter-${i}`}>{String.fromCharCode(65+i)}</span>{chosen && <CheckCircle2 size={17} className="option-check"/>}</div><b>{optionName(o.label)}</b><span className="option-sub">{optionDescription(o.label)}</span><div className="option-value">{fmt(m.value)} <small>plan value</small></div><div className="option-metrics"><span><Check size={13}/> {m.missions ?? o.plan?.assignments?.length ?? 0} missions</span><span><RefreshCw size={13}/> {m.sorties_changed ?? 0} changes</span></div><div className="option-bottom"><span>Stability</span><b>{m.stability != null ? `${Math.round(m.stability*100)}%` : '—'}</b></div><div className="progress-track"><div className="progress-fill" style={{width:`${Math.max(0,Math.min(100,(m.stability||0)*100))}%`}}/></div></button>})}</div>{selectedOption && <div className="selected-option-details"><div><b>{optionName(selectedOption)} selected for review</b><span>{metrics?.robustness != null ? `Resilience score ${Math.round(metrics.robustness)} / 100` : 'Compare assignment coverage, stability and changes before applying.'}</span></div><div className="selected-option-metrics"><Detail label="Plan value" value={fmt(metrics?.value)}/><Detail label="Missions covered" value={metrics?.missions ?? '—'}/><Detail label="Assignments changed" value={metrics?.sorties_changed ?? '—'}/><Detail label="Reported issues" value={metrics?.violations ?? '—'}/></div></div>}<label className="reason-label">Review note<input value={reason} onChange={e => setReason(e.target.value)} placeholder="Add a short reason for this decision"/></label>{isApprover ? <div className="modal-actions left-actions"><Button variant="primary" icon={CheckCircle2} onClick={() => onDecide('approve',selectedOption)} disabled={busy || !selectedOption || job?.type !== 'replan_options' || job?.status !== 'COMPLETED'}>Apply selected plan</Button><Button icon={X} onClick={() => onDecide('reject',selectedOption)} disabled={busy || !selectedOption || job?.type !== 'replan_options' || job?.status !== 'COMPLETED'}>Reject option</Button></div> : <div className="role-note"><ShieldCheck size={16}/> {isPlanner ? 'You can compare plans. An approver must apply or reject an option.' : 'You have read-only access. Ask a planner to generate options and an approver to review them.'}</div>}</section>}
    </div><aside className="lab-side"><section className="panel side-panel"><div className="side-panel-head"><div className="side-icon blue"><Compass size={18}/></div><div><h3>Current scenario</h3><span>Version {current?.version_no}</span></div></div><div className="side-kv"><span>Missions</span><b>{state?.missions?.length || 0}</b></div><div className="side-kv"><span>Aircraft records</span><b>{state?.aircraft?.length || 0}</b></div><div className="side-kv"><span>Crew records</span><b>{state?.crew?.length || 0}</b></div><div className="side-kv"><span>Current assignments</span><b>{plan?.assignments?.length || 0}</b></div><div className="side-divider"/><p className="side-note"><ShieldCheck size={15}/> Applying an option creates a new saved version. The previous version remains available in history.</p></section><section className="panel side-panel"><div className="side-panel-head"><div className="side-icon teal"><Clock3 size={18}/></div><div><h3>Review sequence</h3><span>Recommended workflow</span></div></div><ReviewStep n="1" title="Add change" text="Choose a sample or enter an event." active={events.length>0}/><ReviewStep n="2" title="Assess impact" text="Review affected activity and constraints." active={!!impact}/><ReviewStep n="3" title="Compare options" text="Generate and inspect alternatives." active={!!result}/><ReviewStep n="4" title="Human decision" text="An approver applies or rejects." active={false}/></section></aside></div></>
}
function ReviewStep({ n, title, text, active }) { return <div className="review-step"><div className={`review-step-n ${active?'done':''}`}>{active?<Check size={13}/>:n}</div><div><b>{title}</b><span>{text}</span></div></div> }
function eventTitle(e) { return ({WEATHER:'Weather change',AIRCRAFT_OUT:'Aircraft unavailable',CREW_OUT:'Crew unavailable',THREAT_POPUP:'New sector risk',RUNWAY_CLOSED:'Base closure',PRIORITY_CHANGE:'Priority updated',NEW_MISSION:'New mission'})[e.type] || pretty(e.type) }
function eventDescription(e) { if(e.type==='WEATHER') return `${e.sector} · severity ${e.severity}`; if(e.type==='THREAT_POPUP') return `${e.sector} · severity ${e.severity}`; if(e.target_id) return e.target_id; return e.sector || 'Scenario-wide' }
function optionName(label) { return ({A_max_value:'Maximum coverage',B_balanced:'Balanced approach',C_stable:'Minimum disruption',greedy_patch:'Quick adjustment'})[label] || pretty(label) }
function optionDescription(label) { return ({A_max_value:'Prioritises retaining more plan value.',B_balanced:'Balances coverage and the amount of change.',C_stable:'Keeps more of the previous assignments.',greedy_patch:'A fast baseline for comparison.'})[label] || 'Alternative plan for review.' }

function Readiness({ state, provenance, busy, onRefresh }) {
  const readings = provenance?.readings || provenance?.records || provenance?.items || []
  const counts = useMemo(() => { const all = Array.isArray(readings) ? readings : Object.values(readings || {}); const resolved = provenance?.resolved || []; return { total: all.length, fresh: resolved.filter(r => String(r.status || '').toUpperCase() === 'FRESH').length, stale: resolved.filter(r => String(r.status || '').toUpperCase() === 'STALE').length, conflicts: resolved.filter(r => r.conflict).length } }, [readings])
  return <><PageHeading eyebrow="SHARED PICTURE" title="Readiness & feeds" description="Understand where the scenario information came from and whether it needs a second look." actions={<Button icon={RefreshCw} onClick={onRefresh} disabled={busy}>{busy?'Refreshing…':'Refresh feeds'}</Button>}/><div className="readiness-banner"><div className="readiness-banner-icon"><Database size={20}/></div><div><b>Simulated data sources</b><p>Feeds are generated for this prototype. They do not connect to live aircraft, weather, crew, or threat systems.</p></div><span className="status-chip neutral">Simulation</span></div><div className="stat-grid"><StatCard label="Feed readings" value={counts.total || '—'} detail="Returned by the current feed view" icon={Database} tone="blue"/><StatCard label="Fresh readings" value={counts.fresh || '—'} detail="Marked fresh by the feed" icon={CheckCircle2} tone="teal"/><StatCard label="Stale readings" value={counts.stale || '—'} detail="May need a refresh or review" icon={Clock3} tone="amber"/><StatCard label="Conflicting readings" value={counts.conflicts || '—'} detail="Flagged for attention" icon={AlertTriangle} tone="purple"/></div><div className="readiness-grid"><section className="panel"><div className="panel-heading"><div><h3>Information sources</h3><p>Data categories represented in the scenario</p></div></div><div className="source-list">{[{icon:Cloud,title:'Weather conditions',desc:'Sector-level conditions and severity',color:'blue'},{icon:Settings2,title:'Aircraft availability',desc:'Serviceability and maintenance windows',color:'teal'},{icon:Users,title:'Crew readiness',desc:'Crew availability, duty and rest windows',color:'purple'},{icon:AlertTriangle,title:'Operational incidents',desc:'Synthetic changes and reported risks',color:'amber'},{icon:MapPinned,title:'Base availability',desc:'Runway capacity and closures',color:'blue'}].map(s=>{const Icon=s.icon;return <div className="source-row" key={s.title}><div className={`source-icon ${s.color}`}><Icon size={18}/></div><div><b>{s.title}</b><span>{s.desc}</span></div><span className="status-chip neutral">Simulated</span></div>})}</div></section><section className="panel"><div className="panel-heading"><div><h3>Scenario readiness</h3><p>Current synthetic dataset size</p></div></div><div className="readiness-counts"><div><span>Mission records</span><b>{state?.missions?.length || 0}</b><small>Activity requiring review</small></div><div><span>Aircraft records</span><b>{state?.aircraft?.length || 0}</b><small>Available resource pool</small></div><div><span>Crew records</span><b>{state?.crew?.length || 0}</b><small>People and qualifications</small></div><div><span>Base records</span><b>{state?.bases?.length || 0}</b><small>Departure locations</small></div></div><div className="feed-note"><CircleHelp size={16}/><span>Large datasets can be explored through a smaller representative view first. Counts shown here describe the active scenario, while the backend continues to use the full scenario it receives.</span></div></section></div><section className="panel feed-detail"><div className="panel-heading"><div><h3>Feed detail</h3><p>Plain-language view of the selected information from each simulated source.</p></div><span className="status-chip neutral">{provenance?.mode === 'simulated' ? 'Simulated mode' : provenance ? 'Response received' : 'Not loaded'}</span></div>{!provenance ? <div className="table-empty"><Database size={22}/><b>No feed snapshot loaded</b><span>Select Refresh feeds to request the latest simulated picture.</span></div> : <ResolvedFeedTable rows={provenance.resolved || []}/>}</section></>
}
function History({ history, versions, isApprover, busy, onRefresh, onRollback, current }) {
  return <><PageHeading eyebrow="ACCOUNTABILITY" title="Decision history" description="Review saved versions, previous decisions, and why a change was recorded." actions={<Button icon={RefreshCw} onClick={onRefresh} disabled={busy}>Refresh history</Button>}/><section className="panel history-panel"><div className="panel-heading"><div><h3>Saved scenario versions</h3><p>Each applied plan or reset creates a version record.</p></div><span className="status-chip neutral">{versions.length} versions</span></div>{versions.length ? <div className="version-list">{[...versions].reverse().map(v=><div className={`version-row ${v.id===current?.version_id?'version-current':''}`} key={v.id}><div className="version-badge">v{v.version_no}</div><div className="version-main"><div><b>Version {v.version_no}</b>{v.id===current?.version_id && <span className="status-chip success">Current</span>}</div><span>{pretty(v.source || 'generated')} · {new Date(v.created_at).toLocaleString()}</span><small className="version-id">{v.id}</small></div><div className="version-actions">{v.id!==current?.version_id && isApprover && <Button icon={RotateCcw} onClick={()=>onRollback(v.id)}>Roll back</Button>}</div></div>)}</div> : <div className="table-empty"><FileClock size={22}/><b>No versions available</b><span>Create a scenario to start a version history.</span></div>}</section><section className="panel history-panel"><div className="panel-heading"><div><h3>Decision log</h3><p>Recorded approvals, rejections, resets, and rollbacks.</p></div><span className="status-chip neutral">{history.length} entries</span></div>{history.length ? <div className="decision-list">{history.map(item=><div className="decision-row" key={item.id}><div className={`decision-icon ${item.action==='approve'?'good':item.action==='reject'?'warn':'neutral'}`}>{item.action==='approve'?<CheckCircle2 size={17}/>:item.action==='reject'?<X size={17}/>:<FileClock size={17}/>}</div><div className="decision-main"><b>{pretty(item.action)}{item.option_label ? ` · ${optionName(item.option_label)}` : ''}</b><span>{item.reason || 'No review note supplied'}</span><small>{item.actor} · {new Date(item.created_at).toLocaleString()}</small></div><span className="decision-version">{item.scenario_version_id ? `Version ref: ${item.scenario_version_id.slice(0,8)}` : '—'}</span></div>)}</div> : <div className="table-empty"><FileClock size={22}/><b>No decisions recorded yet</b><span>Completed review actions will appear here.</span></div>}</section></>
}
function Performance({ evaluation, busy, onRefresh }) {
  const rows = evaluation?.rows || []
  const [showAll, setShowAll] = useState(false)
  const displayKeys = ['size','event','missions','greedy_n','opt_n','affected','patch_retained','scratch_retained','minchurn_retained','opt_status'].filter(k => rows.some(r => Object.prototype.hasOwnProperty.call(r,k)))
  const shown = showAll ? rows : rows.slice(0, 12)
  const avg = key => { const values = rows.map(r => Number(r[key])).filter(Number.isFinite); return values.length ? values.reduce((a,b)=>a+b,0)/values.length : null }
  const averageMissions = avg('missions')
  const averageCovered = avg('opt_n')
  const averageAffected = avg('affected')
  const labels = { size:'Scenario size', event:'Simulated change', missions:'Missions', greedy_n:'Initial coverage', opt_n:'Improved coverage', affected:'Affected missions', patch_retained:'Quick adjustment retained', scratch_retained:'Rebuilt plan retained', minchurn_retained:'Stable plan retained', opt_status:'Result' }
  const valueFor = (key, row) => {
    const value = row[key]
    if (value == null || value === '') return '—'
    if (key.endsWith('_retained')) return `${Number(value).toFixed(1)}%`
    if (key === 'event') return pretty(value)
    if (key === 'opt_status') return ({OPTIMAL:'Complete', FEASIBLE:'Available', GREEDY:'Quick baseline', UNKNOWN:'Not available'})[value] || pretty(value)
    if (key === 'size') return ({S:'Small',M:'Medium',L:'Large',XL:'Extra large'})[value] || value
    return value
  }
  return <><PageHeading eyebrow="RESULTS & LEARNING" title="Performance" description="Review saved benchmark results and inspect the full returned dataset." actions={<Button icon={RefreshCw} onClick={onRefresh} disabled={busy}>Refresh results</Button>}/><div className="readiness-banner"><div className="readiness-banner-icon"><Gauge size={20}/></div><div><b>Benchmark results are separate from current scenario state</b><p>These saved test runs help evaluate the prototype. They are not guarantees of real-world performance.</p></div><span className="status-chip neutral">{evaluation?.source || 'No source'}</span></div><div className="stat-grid"><StatCard label="Saved test runs" value={evaluation?.count ?? '—'} detail="All rows included in summary calculations" icon={Activity} tone="blue"/><StatCard label="Average missions" value={averageMissions != null ? averageMissions.toFixed(1) : '—'} detail="Across the full available result set" icon={Target} tone="teal"/><StatCard label="Average improved coverage" value={averageCovered != null ? averageCovered.toFixed(1) : '—'} detail="Missions assigned per test run" icon={CheckCircle2} tone="purple"/><StatCard label="Average affected missions" value={averageAffected != null ? averageAffected.toFixed(1) : '—'} detail="In the saved disruption tests" icon={AlertTriangle} tone="amber"/></div><section className="panel table-panel"><div className="panel-heading"><div><h3>Benchmark results</h3><p>Showing {shown.length} of {rows.length} saved test runs. Summary cards above use every returned row.</p></div><Button icon={showAll ? ChevronLeft : Layers3} onClick={() => setShowAll(v=>!v)} disabled={rows.length <= 12}>{showAll ? 'Show first 12' : 'Show all results'}</Button></div>{rows.length ? <div className="table-scroll"><table className="data-table benchmark-table"><thead><tr>{displayKeys.map(k=><th key={k}>{labels[k] || pretty(k)}</th>)}</tr></thead><tbody>{shown.map((r,i)=><tr key={i}>{displayKeys.map(k=><td key={k}>{valueFor(k,r)}</td>)}</tr>)}</tbody></table></div> : <div className="table-empty"><Gauge size={22}/><b>No benchmark data available</b><span>Check the backend evaluation directory and refresh.</span></div>}</section><div className="disclaimer"><Database size={15}/><span>The first 12 rows are shown by default for readability. Selecting “Show all results” displays the rest of the returned dataset without changing the backend or its evaluation process.</span></div></>
}

function ResolvedFeedTable({ rows }) {
  if (!rows.length) return <div className="table-empty"><Database size={22}/><b>No resolved feed entries</b><span>The API returned a feed snapshot with no resolved readings.</span></div>
  return <div className="table-scroll"><table className="data-table"><thead><tr><th>Information type</th><th>Item</th><th>Freshness</th><th>Conflicting reports</th><th>Confidence</th><th>Source</th></tr></thead><tbody>{rows.slice(0, 20).map((r,i)=>{const c=r.chosen||{};return <tr key={`${r.kind}-${r.key}-${i}`}><td>{({weather:'Weather',weather_escalation:'Weather change',aircraft_fault:'Aircraft availability',crew_fault:'Crew availability',threat:'Sector risk',maintenance:'Maintenance',incident:'Incident report'})[r.kind] || pretty(r.kind)}</td><td>{r.key || 'Scenario'}</td><td><span className={`status-chip ${r.status==='FRESH'?'success':'warning'}`}>{r.status==='FRESH'?'Fresh':'Needs review'}</span></td><td>{r.conflict?'Yes':'No'}</td><td>{c.confidence != null ? `${Math.round(Number(c.confidence)*100)}%` : '—'}</td><td>{c.source || 'Simulated feed'}</td></tr>})}</tbody></table>{rows.length>20 && <div className="table-more-note">Showing the first 20 resolved entries for readability. The complete feed snapshot remains available to the backend.</div>}</div>
}

function Modal({ title, subtitle, children, onClose }) { return <div className="modal-backdrop" onMouseDown={e => e.target===e.currentTarget && onClose()}><div className="modal"><div className="modal-head"><div><h2>{title}</h2><p>{subtitle}</p></div><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={18}/></button></div>{children}</div></div> }

export default App
