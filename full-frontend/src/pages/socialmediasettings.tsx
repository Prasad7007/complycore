import * as React from "react"
import { createPortal } from "react-dom"
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Loader2,
  Pause,
  Play,
  Plus,
  Trash2,
  X,
} from "lucide-react"
import { Navigate, useParams } from "react-router-dom"

import { MainLayout } from "@/components/layout/MainLayout"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { monitoringApi, type MonitoredProfile } from "@/lib/api"

// ── Helpers ───────────────────────────────────────────────────────

function getPageRange(current: number, total: number, windowSize = 5) {
  const half = Math.floor(windowSize / 2)
  let start = Math.max(1, current - half)
  const end = Math.min(total, start + windowSize - 1)
  start = Math.max(1, end - windowSize + 1)
  return Array.from({ length: end - start + 1 }, (_, i) => start + i)
}

function formatDate(iso: string | null) {
  if (!iso) return "—"
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
}

function formatDateTime(iso: string | null) {
  if (!iso) return "Never"
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
}

// ── Sub-components ────────────────────────────────────────────────

function StatusBadge({ status }: { status: "active" | "paused" }) {
  return status === "active" ? (
    <span className="inline-flex items-center rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium whitespace-nowrap text-emerald-700 dark:border-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400">
      Active
    </span>
  ) : (
    <span className="inline-flex items-center rounded-lg border border-gray-200 bg-gray-100 px-2.5 py-0.5 text-xs font-medium whitespace-nowrap text-gray-500 dark:border-border dark:bg-muted dark:text-muted-foreground">
      Paused
    </span>
  )
}

function FlaggedCell({ count }: { count: number }) {
  return (
    <div className="flex items-center gap-1 text-xs text-red-500">
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
      <span className="font-medium">{count}</span>
    </div>
  )
}

// ── Detail Modal ──────────────────────────────────────────────────

function ProfileDetailModal({
  profile,
  onClose,
  onToggleStatus,
}: {
  profile: MonitoredProfile
  onClose: () => void
  onToggleStatus: (id: string, current: "active" | "paused") => Promise<void>
}) {
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose()
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  const fields: { label: string; value: React.ReactNode }[] = [
    { label: "Profile", value: <span className="font-medium">{profile.display_name}</span> },
    {
      label: "URL",
      value: (
        <a href={profile.url} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-[#128BDA] hover:underline">
          View Profile <ExternalLink className="h-3 w-3" />
        </a>
      ),
    },
    { label: "Added", value: formatDate(profile.created_at) },
    { label: "Frequency", value: profile.check_frequency },
    { label: "Timing", value: profile.check_time ?? "—" },
    { label: "Last Checked", value: formatDateTime(profile.last_checked_at) },
    { label: "Posts Reviewed", value: profile.posts_reviewed },
    { label: "Flagged", value: <FlaggedCell count={profile.flagged_posts} /> },
    { label: "Status", value: <StatusBadge status={profile.status} /> },
  ]

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-sm px-4"
      role="dialog" aria-modal="true" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="w-full max-w-md rounded-xl border border-border bg-card shadow-[0_24px_80px_rgba(16,24,40,0.22)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.45)]">
        <div className="flex items-center justify-between border-b border-foreground/[0.07] px-5 py-4">
          <div>
            <div className="text-sm font-semibold text-foreground">Profile Details</div>
            <div className="mt-0.5 text-xs text-muted-foreground">{profile.display_name}</div>
          </div>
          <button type="button" onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="divide-y divide-foreground/[0.06] px-5">
          {fields.map((f) => (
            <div key={f.label} className="flex items-center justify-between gap-4 py-3">
              <span className="text-xs text-muted-foreground">{f.label}</span>
              <span className="text-xs text-foreground">{f.value}</span>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-foreground/[0.07] px-5 py-4">
          {profile.status === "paused" ? (
            <button type="button"
              onClick={() => onToggleStatus(profile.id, profile.status).then(onClose)}
              className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-600/90">
              <Play className="h-3.5 w-3.5" /> Resume
            </button>
          ) : (
            <button type="button"
              onClick={() => onToggleStatus(profile.id, profile.status).then(onClose)}
              className="flex items-center gap-1.5 rounded-lg bg-[#128BDA] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#128BDA]/90">
              <Pause className="h-3.5 w-3.5" /> Pause
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}

// ── Email Digest Modal ─────────────────────────────────────────────

type EmailRecipient = { id: string; email: string }

function stringToColor(s: string) {
  let h = 0
  for (let i = 0; i < s.length; i++) h = s.charCodeAt(i) + ((h << 5) - h)
  return `hsl(${Math.abs(h) % 360},55%,55%)`
}

function RecipientAvatar({ email }: { email: string }) {
  const initials = email.slice(0, 2).toUpperCase()
  return (
    <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[11px] font-semibold text-white"
      style={{ background: stringToColor(email) }}>
      {initials}
    </div>
  )
}

function EmailDigestModal({
  onClose,
  initialRecipients,
  onSave,
  saving,
  loading,
}: {
  onClose: () => void
  initialRecipients: EmailRecipient[]
  onSave: (recipients: EmailRecipient[]) => Promise<void>
  saving: boolean
  loading: boolean
}) {
  const [inputValue, setInputValue] = React.useState("")
  const [recipients, setRecipients] = React.useState<EmailRecipient[]>(initialRecipients)

  React.useEffect(() => {
    setRecipients(initialRecipients)
    // Keep the UI tidy: don't prefill the email input.
    setInputValue("")
  }, [initialRecipients])

  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    window.addEventListener("keydown", onKeyDown)
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => { window.removeEventListener("keydown", onKeyDown); document.body.style.overflow = prev }
  }, [onClose])

  function handleAdd() {
    const trimmed = inputValue.trim()
    if (!trimmed) return
    setRecipients((prev) => [...prev, { id: Date.now().toString(), email: trimmed }])
    setInputValue("")
  }

  if (typeof document === "undefined") return null

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-sm"
      role="dialog" aria-modal="true" aria-label="Email Digest Settings"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="w-[min(520px,calc(100vw-32px))] rounded-xl border border-border bg-card shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.45)]">
        <div className="flex items-start justify-between gap-4 px-6 pt-6">
          <div>
            <div className="text-base font-semibold text-foreground">Email Digest Settings</div>
            <div className="mt-1 text-xs text-muted-foreground">Configure email notifications for compliance review summaries.</div>
          </div>
          <button type="button" onClick={onClose}
            className="grid h-9 w-9 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Close">
            <span className="text-xl leading-none">×</span>
          </button>
        </div>
        <div className="px-6 pb-6 pt-5">
          {loading && (
            <div className="mb-4 text-xs text-muted-foreground">Loading saved recipients...</div>
          )}
          <label className="mb-2 block text-sm font-semibold text-foreground">Email Recipients</label>
          <div className="flex gap-2">
            <Input type="email" placeholder="admin@company.com" value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleAdd() } }}
              className="flex-1" />
            <button type="button" onClick={handleAdd}
              className="rounded-lg bg-[#128BDA] px-5 py-2 text-sm font-medium text-white hover:bg-[#128BDA]/90">Add</button>
          </div>
          <div className="mt-4 divide-y divide-foreground/[0.07]">
            {recipients.map((r) => (
              <div key={r.id} className="flex items-center justify-between py-3">
                <div className="flex items-center gap-3">
                  <RecipientAvatar email={r.email} />
                  <span className="text-sm text-foreground">{r.email}</span>
                </div>
                <button type="button" onClick={() => setRecipients((prev) => prev.filter((x) => x.id !== r.id))}
                  className="rounded-md p-1 text-red-500 hover:bg-red-500/10 dark:hover:bg-red-950/40" aria-label="Remove recipient">
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
          <div className="mt-5 flex justify-end gap-3">
            <button type="button" onClick={onClose}
              className="h-9 rounded-lg border border-input bg-background px-5 text-xs font-medium text-foreground hover:bg-muted">Cancel</button>
            <button
              type="button"
              onClick={() => onSave(recipients)}
              disabled={saving || loading || recipients.length === 0}
              className="h-9 rounded-lg bg-[#128BDA] px-5 text-xs font-semibold text-white hover:bg-[#128BDA]/90 disabled:opacity-60"
            >
              {saving ? "Saving..." : "Save Setting"}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

// ── Add LinkedIn Profile Modal ────────────────────────────────────

function AddProfileModal({
  orgSlug,
  onClose,
  onAdded,
}: {
  orgSlug: string
  onClose: () => void
  onAdded: (profile: MonitoredProfile) => void
}) {
  const [linkedinUrl, setLinkedinUrl] = React.useState("")
  const [displayName, setDisplayName] = React.useState("")
  const [frequency, setFrequency] = React.useState("daily")
  const [hour, setHour] = React.useState("09")
  const [minute, setMinute] = React.useState("00")
  const [period, setPeriod] = React.useState<"AM" | "PM">("AM")
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    window.addEventListener("keydown", onKeyDown)
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => { window.removeEventListener("keydown", onKeyDown); document.body.style.overflow = prev }
  }, [onClose])

  async function handleSubmit() {
    if (!linkedinUrl.trim()) { setError("LinkedIn URL is required"); return }
    setLoading(true); setError(null)
    try {
      // Convert 12h → 24h for Postgres TIME column
      let h = parseInt(hour) || 0
      if (period === "AM" && h === 12) h = 0
      if (period === "PM" && h !== 12) h += 12
      const check_time = `${String(h).padStart(2, "0")}:${minute.padStart(2, "0")}`

      const profile = await monitoringApi.createProfile(orgSlug, {
        url: linkedinUrl.trim(),
        display_name: displayName.trim() || linkedinUrl.trim(),
        status: "active",
        check_frequency: frequency,
        check_time,
      })
      onAdded(profile)
      onClose()
    } catch (e: any) {
      setError(e.message || "Failed to add profile")
    } finally {
      setLoading(false)
    }
  }

  if (typeof document === "undefined") return null

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-sm"
      role="dialog" aria-modal="true" aria-label="Add LinkedIn Profile"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="w-[min(520px,calc(100vw-32px))] rounded-xl border border-border bg-card shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.45)]">
        <div className="flex items-start justify-between gap-4 px-6 pt-6">
          <div>
            <div className="text-base font-semibold text-foreground">Add LinkedIn Profile</div>
            <div className="mt-1 text-xs text-muted-foreground">Enter a LinkedIn profile or company page URL to monitor for compliance.</div>
          </div>
          <button type="button" onClick={onClose}
            className="grid h-9 w-9 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Close">
            <span className="text-xl leading-none">×</span>
          </button>
        </div>
        <div className="px-6 pb-6 pt-5 space-y-4">
          {error && <p className="rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-600 dark:text-red-400">{error}</p>}
          <div>
            <label className="mb-1.5 block text-sm font-semibold text-foreground">LinkedIn URL</label>
            <Input type="url" placeholder="https://linkedin.com/company/your-company"
              value={linkedinUrl} onChange={(e) => setLinkedinUrl(e.target.value)} />
            <p className="mt-1 text-[11px] text-muted-foreground">Supports profile URLs (linkedin.com/in/...) and company pages (linkedin.com/company/...)</p>
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-semibold text-foreground">
              Display Name <span className="font-normal text-muted-foreground">(Optional)</span>
            </label>
            <Input type="text" placeholder="ACME Wealth Management"
              value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </div>
          <div className="flex items-end gap-4">
            <div className="flex-1">
              <label className="mb-1.5 block text-sm font-semibold text-foreground">Check Frequency</label>
              <div className="relative">
                <select value={frequency} onChange={(e) => setFrequency(e.target.value)}
                  className="w-full appearance-none rounded-lg border border-input bg-background px-3 py-2 pr-8 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-[#128BDA]/30">
                  <option value="daily">Daily</option>
                </select>
                <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground">⌄</span>
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-semibold text-foreground">Check Time</label>
              <div className="flex items-center gap-1">
                <input type="text" maxLength={2} value={hour}
                  onChange={(e) => setHour(e.target.value.replace(/\D/g, "").slice(0, 2))}
                  className="w-12 rounded-lg border border-input bg-background px-2 py-2 text-center text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-[#128BDA]/30" />
                <span className="text-muted-foreground">:</span>
                <input type="text" maxLength={2} value={minute}
                  onChange={(e) => setMinute(e.target.value.replace(/\D/g, "").slice(0, 2))}
                  className="w-12 rounded-lg border border-input bg-background px-2 py-2 text-center text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-[#128BDA]/30" />
                <div className="relative">
                  <select value={period} onChange={(e) => setPeriod(e.target.value as "AM" | "PM")}
                    className="appearance-none rounded-lg border border-input bg-background px-2 py-2 pr-6 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-[#128BDA]/30">
                    <option>AM</option>
                    <option>PM</option>
                  </select>
                  <span className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground">⌄</span>
                </div>
              </div>
            </div>
          </div>
          <div className="flex justify-end gap-3 pt-1">
            <button type="button" onClick={onClose}
              className="h-9 rounded-lg border border-input bg-background px-5 text-xs font-medium text-foreground hover:bg-muted">Cancel</button>
            <button type="button" onClick={handleSubmit} disabled={loading}
              className="flex h-9 items-center gap-2 rounded-lg bg-[#128BDA] px-5 text-xs font-semibold text-white hover:bg-[#128BDA]/90 disabled:opacity-60">
              {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Add Profile
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

// ── Main Page ─────────────────────────────────────────────────────

const PAGE_SIZE = 12

export default function SocialMediaSettingsPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>()
  const [headerSearch, setHeaderSearch] = React.useState("")
  const [profiles, setProfiles] = React.useState<MonitoredProfile[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [page, setPage] = React.useState(1)
  const [detailProfile, setDetailProfile] = React.useState<MonitoredProfile | null>(null)
  const [emailDigestOpen, setEmailDigestOpen] = React.useState(false)
  const [emailDigestLoading, setEmailDigestLoading] = React.useState(false)
  const [emailDigestSaving, setEmailDigestSaving] = React.useState(false)
  const [emailDigestRecipients, setEmailDigestRecipients] = React.useState<EmailRecipient[]>([])
  const [emailDigestError, setEmailDigestError] = React.useState<string | null>(null)
  const [addProfileOpen, setAddProfileOpen] = React.useState(false)
  const [runningId, setRunningId] = React.useState<string | null>(null)
  const [runResult, setRunResult] = React.useState<{ id: string; message: string; status: string } | null>(null)

  // Fetch profiles on mount
  React.useEffect(() => {
    if (!orgSlug?.trim()) {
      setLoading(false)
      return
    }
    monitoringApi.listProfiles(orgSlug)
      .then(setProfiles)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [orgSlug])

  async function loadEmailDigestSettings() {
    if (!orgSlug?.trim()) return
    setEmailDigestError(null)
    setEmailDigestLoading(true)
    try {
      const res = await monitoringApi.getDigestSettings(orgSlug)
      setEmailDigestRecipients(
        (res.recipients || []).map((r) => ({
          id: r.id,
          email: r.email,
        })),
      )
    } catch (e: any) {
      setEmailDigestError(e.message || "Failed to load digest settings")
    } finally {
      setEmailDigestLoading(false)
    }
  }

  async function saveEmailDigestSettings(recipients: EmailRecipient[]) {
    if (!orgSlug?.trim()) return
    setEmailDigestSaving(true)
    setEmailDigestError(null)
    try {
      await monitoringApi.updateDigestSettings(orgSlug, {
        enabled: true,
        recipients: recipients.map((r) => r.email),
      })
      await loadEmailDigestSettings()
      setEmailDigestOpen(false)
    } catch (e: any) {
      setEmailDigestError(e.message || "Failed to save digest settings")
    } finally {
      setEmailDigestSaving(false)
    }
  }

  async function handleToggleStatus(id: string, current: "active" | "paused") {
    if (!orgSlug?.trim()) return
    const next = current === "active" ? "paused" : "active"
    const updated = await monitoringApi.updateProfile(orgSlug, id, { status: next })
    setProfiles((prev) => prev.map((p) => p.id === id ? updated : p))
  }

  async function handleDelete(id: string) {
    if (!orgSlug?.trim()) return
    await monitoringApi.deleteProfile(orgSlug, id)
    setProfiles((prev) => prev.filter((p) => p.id !== id))
  }

  function handleAdded(profile: MonitoredProfile) {
    setProfiles((prev) => [profile, ...prev])
    setPage(1)
  }

  async function handleRunProfile(id: string) {
    if (!orgSlug?.trim()) return
    setRunningId(id)
    setRunResult(null)
    try {
      const res = await monitoringApi.runProfile(orgSlug, id)
      // Refresh the profile row so last_checked_at / stats update
      const updated = await monitoringApi.listProfiles(orgSlug)
      setProfiles(updated)
      setRunResult({ id, status: res.status, message: res.message })
    } catch (e: any) {
      setRunResult({ id, status: "error", message: e.message })
    } finally {
      setRunningId(null)
    }
  }

  const filteredProfiles = React.useMemo(() => {
    const q = headerSearch.trim().toLowerCase()
    if (!q) return profiles
    return profiles.filter((p) => (p.display_name || "").toLowerCase().includes(q))
  }, [headerSearch, profiles])

  React.useEffect(() => {
    setPage(1)
  }, [filteredProfiles.length])

  const totalPages = Math.max(1, Math.ceil(filteredProfiles.length / PAGE_SIZE))
  const pageRows = filteredProfiles.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const thBase = "border-b border-r border-foreground/10 px-3 py-2.5 text-left text-xs font-normal text-foreground/50 whitespace-nowrap"
  const thLast = "border-b border-foreground/10 px-3 py-2.5 text-left text-xs font-normal text-foreground/50 whitespace-nowrap"

  if (!orgSlug?.trim()) {
    return <Navigate to="/pending-access" replace />
  }

  return (
    <MainLayout header={{
      breadcrumbs: [{ label: "ComplyCore", to: `/orgs/${encodeURIComponent(orgSlug)}/dashboard/default` }, { label: "Social Media Settings" }],
      searchQuery: headerSearch,
      onSearchChange: setHeaderSearch,
      searchPlaceholder: "Search profiles",
    }}>
      <div className="space-y-6">
        <div>
          <div className="text-sm font-semibold text-foreground">Social Media settings</div>
          <div className="mt-1 text-xs text-muted-foreground">Manage LinkedIn profile monitoring and automated compliance analysis</div>
        </div>

        <div className="rounded-xl border border-border bg-card shadow-sm dark:shadow-[-4px_4px_12px_rgba(0,0,0,0.3)]">
          {/* Header */}
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-foreground/[0.07] px-5 py-4">
            <div>
              <div className="text-sm font-semibold text-foreground">LinkedIn Profiles</div>
              <div className="mt-0.5 text-xs text-muted-foreground">Manage LinkedIn profiles and company pages being monitored for compliance.</div>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" className="h-9 gap-2 text-xs font-medium" type="button"
                onClick={async () => {
                  setEmailDigestOpen(true)
                  await loadEmailDigestSettings()
                }}>
                <img
                  src="/shared/emailIcon.svg"
                  alt="email"
                  className="h-3.5 w-3.5 shrink-0 dark:invert"
                />
                Email Digest
              </Button>
              <Button size="sm" className="h-9 gap-2 bg-[#128BDA] text-xs font-medium text-white hover:bg-[#128BDA]/90"
                type="button" onClick={() => setAddProfileOpen(true)}>
                <Plus className="h-3.5 w-3.5" /> Add Profile
              </Button>
            </div>
          </div>

          {/* Loading / error states */}
          {loading && (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading profiles...
            </div>
          )}
          {!loading && error && (
            <div className="px-5 py-8 text-center text-sm text-red-500">{error}</div>
          )}
          {!loading && !error && filteredProfiles.length === 0 && (
            <div className="px-5 py-12 text-center text-sm text-muted-foreground">
              No profiles monitored yet. Click "Add Profile" to get started.
            </div>
          )}

          {/* Run result banner */}
          {runResult && (
            <div className={cn(
              "mx-5 mt-4 flex items-center justify-between rounded-lg px-4 py-2.5 text-xs",
              runResult.status === "processed"
                ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400"
                : runResult.status === "error"
                  ? "bg-red-50 text-red-600 dark:bg-red-950/40 dark:text-red-400"
                  : "bg-gray-50 text-gray-600 dark:bg-muted dark:text-muted-foreground"
            )}>
              <span>{runResult.message}</span>
              <button type="button" onClick={() => setRunResult(null)} className="ml-4 opacity-60 hover:opacity-100">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}

          {/* Table */}
          {!loading && !error && filteredProfiles.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-sm">
                <thead className="bg-muted/30">
                  <tr>
                    <th className={thBase}>Profile</th>
                    <th className={cn(thBase, "hidden md:table-cell")}>URL</th>
                    <th className={cn(thBase, "hidden lg:table-cell")}>Added</th>
                    <th className={cn(thBase, "hidden lg:table-cell")}>Frequency</th>
                    <th className={cn(thBase, "hidden lg:table-cell")}>Timing</th>
                    <th className={cn(thBase, "hidden lg:table-cell")}>Last Checked</th>
                    <th className={cn(thBase, "hidden lg:table-cell")}>Posts Reviewed</th>
                    <th className={cn(thBase, "hidden md:table-cell")}>Flagged</th>
                    <th className={thBase}>Status</th>
                    <th className={thLast}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((r) => (
                    <tr key={r.id} className="border-b border-foreground/[0.06] hover:bg-muted/50">
                      <td className="px-3 py-3 text-xs font-medium text-foreground whitespace-nowrap">
                        {r.display_name}
                        <div className="mt-1 space-y-0.5 text-muted-foreground md:hidden">
                          <div>{formatDate(r.created_at)} · {r.check_frequency}</div>
                          <div>{formatDateTime(r.last_checked_at)}</div>
                        </div>
                      </td>
                      <td className="hidden px-3 py-3 md:table-cell">
                        <a href={r.url} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-[#128BDA] hover:underline whitespace-nowrap">
                          View Profile <ExternalLink className="h-3 w-3 shrink-0" />
                        </a>
                      </td>
                      <td className="hidden px-3 py-3 text-xs text-muted-foreground whitespace-nowrap lg:table-cell">{formatDate(r.created_at)}</td>
                      <td className="hidden px-3 py-3 text-xs text-muted-foreground lg:table-cell capitalize">{r.check_frequency}</td>
                      <td className="hidden px-3 py-3 text-xs text-muted-foreground whitespace-nowrap lg:table-cell">{r.check_time ?? "—"}</td>
                      <td className="hidden px-3 py-3 text-xs text-muted-foreground whitespace-nowrap lg:table-cell">{formatDateTime(r.last_checked_at)}</td>
                      <td className="hidden px-3 py-3 text-center text-xs text-muted-foreground lg:table-cell">{r.posts_reviewed}</td>
                      <td className="hidden px-3 py-3 md:table-cell"><FlaggedCell count={r.flagged_posts} /></td>
                      <td className="px-3 py-3"><StatusBadge status={r.status} /></td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-1">
                          <button type="button" title={r.status === "paused" ? "Resume" : "Pause"}
                            onClick={() => handleToggleStatus(r.id, r.status)}
                            className="hidden items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground md:flex">
                            {r.status === "paused" ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
                            <span className="hidden lg:inline">{r.status === "paused" ? "Resume" : "Pause"}</span>
                          </button>
                          <button type="button" title="Delete" onClick={() => handleDelete(r.id)}
                            className="hidden items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs text-red-500 hover:bg-accent md:flex">
                            <Trash2 className="h-3 w-3" />
                            <span className="hidden lg:inline">Delete</span>
                          </button>
                          <button type="button" onClick={() => setDetailProfile(r)}
                            className="flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground md:hidden">
                            Details
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination */}
          {!loading && filteredProfiles.length > PAGE_SIZE && (
            <div className="flex items-center justify-end gap-2 px-4 py-3 md:px-6">
              <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}
                className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50" aria-label="Previous page">
                <ChevronLeft className="h-4 w-4" />
              </button>
              {getPageRange(page, totalPages).map((p) => (
                <button key={p} type="button" onClick={() => setPage(p)} aria-current={p === page ? "page" : undefined}
                  className={cn("grid h-8 w-8 place-items-center rounded-md text-sm",
                    p === page ? "bg-foreground/5 text-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground")}>
                  {p}
                </button>
              ))}
              <button type="button" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
                className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50" aria-label="Next page">
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </div>

      {detailProfile && (
        <ProfileDetailModal profile={detailProfile} onClose={() => setDetailProfile(null)}
          onToggleStatus={handleToggleStatus} />
      )}
      {emailDigestOpen && (
        <EmailDigestModal
          onClose={() => setEmailDigestOpen(false)}
          initialRecipients={emailDigestRecipients}
          onSave={saveEmailDigestSettings}
          saving={emailDigestSaving}
          loading={emailDigestLoading}
        />
      )}
      {emailDigestError && emailDigestOpen && (
        <div className="px-5 pb-5 text-xs text-red-500">{emailDigestError}</div>
      )}
      {addProfileOpen && <AddProfileModal orgSlug={orgSlug} onClose={() => setAddProfileOpen(false)} onAdded={handleAdded} />}
    </MainLayout>
  )
}