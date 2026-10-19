import * as React from "react"

import { MainLayout } from "@/components/layout/MainLayout"
import {
  organizationsApi,
  type OrganizationListItem,
  type OrganizationUploadQuotaSettingsResponse,
  type SuperAdminResponse,
} from "@/lib/api"
import { PasswordValidation } from "@/components/auth/PasswordValidation"
import { ConfirmationModal } from "@/components/models/ConfirmationModal"
import { apiFetch } from "@/lib/api"

const BYTES_PER_GIB = 1024 * 1024 * 1024
const LEGACY_DEFAULT_ORG_SLUG = "legacy-default"

function bytesToGiBString(bytes: number) {
  return (bytes / BYTES_PER_GIB).toFixed(2)
}

function gibStringToBytes(value: string) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return 0
  return Math.round(n * BYTES_PER_GIB)
}

function formatDate(iso: string) {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

function isoToLocalInput(iso: string) {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function localInputToIso(value: string) {
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? new Date().toISOString() : d.toISOString()
}

function canManageQuota(row: OrganizationListItem | null | undefined) {
  return Boolean(row && row.slug !== LEGACY_DEFAULT_ORG_SLUG)
}

function getErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof Error) {
    const lower = e.message.toLowerCase()
    if (lower.includes("fetch") || lower.includes("network")) {
      return "Network error. Please check your connection and try again."
    }
    if (lower.includes("internal server error") || lower.includes("500")) {
      return "Something went wrong on our servers. Please try again later."
    }
    return e.message || fallback
  }
  return fallback
}

export default function OwnerOrganizationsPage() {
  const [rows, setRows] = React.useState<OrganizationListItem[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [selectedOrgId, setSelectedOrgId] = React.useState<string | null>(null)
  const [quotaLoading, setQuotaLoading] = React.useState(false)
  const [quotaBusy, setQuotaBusy] = React.useState(false)
  const [quotaError, setQuotaError] = React.useState<string | null>(null)
  const [quotaNotice, setQuotaNotice] = React.useState<string | null>(null)
  const [quotaState, setQuotaState] = React.useState<OrganizationUploadQuotaSettingsResponse | null>(null)
  const [quotaEnabled, setQuotaEnabled] = React.useState(true)
  const [countLimit, setCountLimit] = React.useState("50")
  const [bytesLimitGiB, setBytesLimitGiB] = React.useState("2.00")
  const [rolloutStartsAt, setRolloutStartsAt] = React.useState("")

  const [superAdmins, setSuperAdmins] = React.useState<SuperAdminResponse[]>([])
  const [superAdminsLoading, setSuperAdminsLoading] = React.useState(false)
  const [superAdminsError, setSuperAdminsError] = React.useState<string | null>(null)

  const [newAdminEmail, setNewAdminEmail] = React.useState("")
  const [newAdminName, setNewAdminName] = React.useState("")
  const [newAdminPassword, setNewAdminPassword] = React.useState("")
  const [newAdminPhone, setNewAdminPhone] = React.useState("")
  const [newAdminBusy, setNewAdminBusy] = React.useState(false)
  const [newAdminError, setNewAdminError] = React.useState<string | null>(null)
  const [adminToDelete, setAdminToDelete] = React.useState<{id: string, name: string} | null>(null)
  const [showCreateAdminWarning, setShowCreateAdminWarning] = React.useState(false)
  const [pendingTasks, setPendingTasks] = React.useState<{id: string, type: string, document_name: string, stage: string}[] | null>(null)
  const [loadingTasks, setLoadingTasks] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    void organizationsApi
      .list()
      .then((data) => {
        if (!cancelled) {
          const nextRows = Array.isArray(data) ? data : []
          setRows(nextRows)
          setSelectedOrgId((current) => {
            const currentRow = nextRows.find((row) => row.id === current)
            if (canManageQuota(currentRow)) return current ?? null
            return null
          })
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(getErrorMessage(e, "We couldn't load the organizations. Please try again."))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  React.useEffect(() => {
    if (!selectedOrgId) {
      setQuotaState(null)
      return
    }
    let cancelled = false
    setQuotaLoading(true)
    setQuotaError(null)
    setQuotaNotice(null)
    void organizationsApi
      .getOrganizationUploadQuotaSettings(selectedOrgId)
      .then((data) => {
        if (cancelled) return
        setQuotaState(data)
        setQuotaEnabled(Boolean(data.quota_enabled))
        setCountLimit(String(data.upload_limit_count))
        setBytesLimitGiB(bytesToGiBString(data.upload_limit_bytes))
        setRolloutStartsAt(isoToLocalInput(data.rollout_starts_at))
      })
      .catch((e: unknown) => {
        if (!cancelled) setQuotaError(getErrorMessage(e, "We couldn't load the organization quota settings."))
      })
      .finally(() => {
        if (!cancelled) setQuotaLoading(false)
      })

    setSuperAdminsLoading(true)
    setSuperAdminsError(null)
    setSuperAdmins([])
    void organizationsApi
      .listSuperAdmins(selectedOrgId)
      .then((data) => {
        if (!cancelled) {
            const sorted = data.sort((a, b) => {
                if (a.is_active && !b.is_active) return -1;
                if (!a.is_active && b.is_active) return 1;
                return a.full_name.localeCompare(b.full_name);
            });
            setSuperAdmins(sorted)
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setSuperAdminsError(getErrorMessage(e, "We couldn't load the super admins."))
      })
      .finally(() => {
        if (!cancelled) setSuperAdminsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [selectedOrgId])

  const selectedOrg = React.useMemo(
    () => rows.find((r) => r.id === selectedOrgId) || null,
    [rows, selectedOrgId]
  )

  const saveQuota = async (event: React.FormEvent) => {
    event.preventDefault()
    const organizationId = selectedOrgId
    if (!canManageQuota(selectedOrg) || !organizationId) return
    setQuotaBusy(true)
    setQuotaError(null)
    setQuotaNotice(null)
    try {
      const res = await organizationsApi.updateOrganizationUploadQuotaSettings(organizationId, {
        quota_enabled: quotaEnabled,
        upload_limit_count: Number(countLimit),
        upload_limit_bytes: gibStringToBytes(bytesLimitGiB),
        rollout_starts_at: localInputToIso(rolloutStartsAt),
      })
      setQuotaState(res)
      setQuotaEnabled(Boolean(res.quota_enabled))
      setCountLimit(String(res.upload_limit_count))
      setBytesLimitGiB(bytesToGiBString(res.upload_limit_bytes))
      setRolloutStartsAt(isoToLocalInput(res.rollout_starts_at))
      setQuotaNotice("Organization quota settings saved.")
    } catch (e: unknown) {
      setQuotaError(getErrorMessage(e, "We couldn't save the quota settings. Please try again."))
    } finally {
      setQuotaBusy(false)
    }
  }

  const resetQuota = async () => {
    const organizationId = selectedOrgId
    if (!canManageQuota(selectedOrg) || !organizationId) return
    setQuotaBusy(true)
    setQuotaError(null)
    setQuotaNotice(null)
    try {
      const res = await organizationsApi.resetOrganizationUploadQuotaSettings(organizationId)
      setQuotaState(res)
      setQuotaEnabled(Boolean(res.quota_enabled))
      setCountLimit(String(res.upload_limit_count))
      setBytesLimitGiB(bytesToGiBString(res.upload_limit_bytes))
      setRolloutStartsAt(isoToLocalInput(res.rollout_starts_at))
      setQuotaNotice("Organization quota settings reset to defaults.")
    } catch (e: unknown) {
      setQuotaError(getErrorMessage(e, "We couldn't reset the quota settings. Please try again."))
    } finally {
      setQuotaBusy(false)
    }
  }

  const handleCreateSuperAdmin = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!selectedOrgId) return
    setShowCreateAdminWarning(true)
  }

  const proceedWithCreateAdmin = async () => {
    if (!selectedOrgId) return
    setNewAdminBusy(true)
    setNewAdminError(null)
    setShowCreateAdminWarning(false)
    try {
      const res = await organizationsApi.createSuperAdmin(selectedOrgId, {
        email: newAdminEmail,
        full_name: newAdminName,
        password: newAdminPassword,
        phone_number: newAdminPhone.trim() || undefined,
      })
      setSuperAdmins((current) => [res, ...current])
      setNewAdminEmail("")
      setNewAdminName("")
      setNewAdminPassword("")
      setNewAdminPhone("")
    } catch (e: unknown) {
      setNewAdminError(getErrorMessage(e, "We couldn't add the super admin. Please try again."))
    } finally {
      setNewAdminBusy(false)
    }
  }

  const handleDeleteSuperAdmin = async (userId: string) => {
    if (!selectedOrgId) return
    
    
    setSuperAdminsLoading(true)
    try {
      await organizationsApi.deleteSuperAdmin(selectedOrgId, userId)
      setSuperAdmins((current) =>
          current.map((admin) =>
              admin.user_id === userId ? { ...admin, is_active: false } : admin
          ).sort((a, b) => {
              if (a.is_active && !b.is_active) return -1;
              if (!a.is_active && b.is_active) return 1;
              return a.full_name.localeCompare(b.full_name);
          })
      )
      setAdminToDelete(null)
    } catch (e: unknown) {
      setSuperAdminsError(getErrorMessage(e, "We couldn't delete the super admin. Please try again."))
    } finally {
      setSuperAdminsLoading(false)
    }
  }

  return (
    <MainLayout
      header={{
        breadcrumbs: [
          { label: "Owner", to: "/owner/multitenancy" },
          { label: "Organizations" },
        ],
      }}
    >
      <div className="space-y-4">
        <div>
          <h1 className="text-lg font-bold text-foreground">Organizations</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            All tenant organizations in the system. Select one below to review or adjust its rollout date and upload limits.
          </p>
        </div>

        {error ? (
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="border-b border-border bg-muted/40">
                <tr>
                  <th className="px-4 py-3 font-semibold text-foreground">Name</th>
                  <th className="px-4 py-3 font-semibold text-foreground">Slug</th>
                  <th className="px-4 py-3 font-semibold text-foreground">Status</th>
                  <th className="px-4 py-3 font-semibold text-foreground">Created</th>
                  <th className="px-4 py-3 font-semibold text-foreground">Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                      Loading…
                    </td>
                  </tr>
                ) : rows.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                      No organizations yet. Create one from Owner Multitenancy.
                    </td>
                  </tr>
                ) : (
                  rows.map((r) => (
                    <tr
                      key={r.id}
                      className={`border-b border-border/80 last:border-0 ${selectedOrgId === r.id ? "bg-muted/30" : ""}`}
                    >
                      <td className="px-4 py-3 font-medium text-foreground">{r.name}</td>
                      <td className="px-4 py-3 text-muted-foreground">{r.slug}</td>
                      <td className="px-4 py-3 text-muted-foreground">{r.status}</td>
                      <td className="px-4 py-3 text-muted-foreground">{formatDate(r.created_at)}</td>
                      <td className="px-4 py-3">
                        {canManageQuota(r) ? (
                          <button
                            type="button"
                            onClick={() => setSelectedOrgId(r.id)}
                            className="rounded-md border border-input bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
                          >
                            Manage org
                          </button>
                        ) : (
                          <span className="text-xs text-muted-foreground">Bypassed</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {selectedOrgId && (
          <form onSubmit={saveQuota} className="space-y-4 rounded-xl border border-border bg-card p-5">
            <div>
              <h2 className="text-base font-semibold text-foreground">Organization Upload Quota</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {selectedOrg
                  ? canManageQuota(selectedOrg)
                    ? `Adjust ${selectedOrg.name}'s quota settings. New orgs start with enabled quota, 50 uploads, 2 GiB, and a rollout date equal to org creation time.`
                    : `${selectedOrg.name} is bypassed from quota enforcement, so quota settings are not managed here.`
                  : "Select an organization to manage its upload quota settings."}
              </p>
            </div>

            {quotaState ? (
              <div className="rounded-md border border-border/70 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                Effective quota: {quotaState.effective_quota.upload_limit_count} uploads /{" "}
                {bytesToGiBString(quotaState.effective_quota.upload_limit_bytes)} GiB, rolling{" "}
                {quotaState.effective_quota.rolling_window_days} days. Rollout starts{" "}
                {formatDate(quotaState.effective_quota.rollout_starts_at)}.
                {quotaState.bypass_active && quotaState.bypass_reason
                  ? ` Bypass active (${quotaState.bypass_reason}).`
                  : ""}
              </div>
            ) : null}

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <label className="text-sm text-foreground">
                Quota enforcement
                <select
                  className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={quotaEnabled ? "enabled" : "disabled"}
                  onChange={(e) => setQuotaEnabled(e.target.value === "enabled")}
                  disabled={!canManageQuota(selectedOrg) || quotaLoading}
                >
                  <option value="enabled">Enabled</option>
                  <option value="disabled">Disabled</option>
                </select>
              </label>

              <label className="text-sm text-foreground">
                Upload limit count
                <input
                  type="number"
                  min={1}
                  className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={countLimit}
                  onChange={(e) => setCountLimit(e.target.value)}
                  disabled={!canManageQuota(selectedOrg) || quotaLoading}
                  required
                />
              </label>

              <label className="text-sm text-foreground">
                Storage limit (GiB)
                <input
                  type="number"
                  min={0.01}
                  step={0.01}
                  className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={bytesLimitGiB}
                  onChange={(e) => setBytesLimitGiB(e.target.value)}
                  disabled={!canManageQuota(selectedOrg) || quotaLoading}
                  required
                />
              </label>

              <label className="text-sm text-foreground">
                Rollout starts at
                <input
                  type="datetime-local"
                  className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={rolloutStartsAt}
                  onChange={(e) => setRolloutStartsAt(e.target.value)}
                  disabled={!canManageQuota(selectedOrg) || quotaLoading}
                  required
                />
              </label>
            </div>

            {quotaState ? (
              <div className="rounded-md border border-border/70 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                Org created {formatDate(quotaState.org_created_at)}. Reset restores quota enabled,{" "}
                {quotaState.defaults.upload_limit_count} uploads, {bytesToGiBString(quotaState.defaults.upload_limit_bytes)} GiB,
                and rollout {formatDate(quotaState.defaults.rollout_starts_at)}.
              </div>
            ) : null}

            {quotaError ? (
              <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                {quotaError}
              </div>
            ) : null}
            {quotaNotice ? (
              <div className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                {quotaNotice}
              </div>
            ) : null}

            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => void resetQuota()}
                disabled={!canManageQuota(selectedOrg) || quotaBusy || quotaLoading}
                className="rounded-md border border-input bg-background px-4 py-2 text-sm font-medium text-foreground disabled:opacity-60"
              >
                Reset to Defaults
              </button>
              <button
                type="submit"
                disabled={!canManageQuota(selectedOrg) || quotaBusy || quotaLoading}
                className="rounded-md bg-gradient-to-r from-[#128ADA] to-[#662CC4] px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
              >
                {quotaBusy ? "Saving..." : "Save Quota Settings"}
              </button>
            </div>
          </form>
        )}

        {/* Super Admins Section */}
        {selectedOrgId && (
          <div className="space-y-4 rounded-xl border border-border bg-card p-5">
            <div>
              <h2 className="text-base font-semibold text-foreground">Organization Super Admins</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Manage the super admins for {selectedOrg?.name}.
              </p>
            </div>

            {superAdminsError ? (
              <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                {superAdminsError}
              </div>
            ) : null}

            {/* List Super Admins */}
            <div className="overflow-hidden rounded-xl border border-border bg-background">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-border bg-muted/40">
                    <tr>
                      <th className="px-4 py-3 font-semibold text-foreground">Name</th>
                      <th className="px-4 py-3 font-semibold text-foreground">Email</th>
                      <th className="px-4 py-3 font-semibold text-foreground">Phone</th>
                      <th className="px-4 py-3 font-semibold text-foreground text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {superAdminsLoading && superAdmins.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">
                          Loading super admins…
                        </td>
                      </tr>
                    ) : superAdmins.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">
                          No super admins found for this organization.
                        </td>
                      </tr>
                    ) : (
                      superAdmins.map((admin, idx) => {
                        const showHeader = !admin.is_active && (idx === 0 || superAdmins[idx - 1].is_active);
                        return (
                        <React.Fragment key={admin.user_id}>
                            {showHeader && (
                                <tr className="bg-muted/10">
                                    <td colSpan={4} className="px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                                        Deactivated Super Admins
                                    </td>
                                </tr>
                            )}
                        <tr className={`border-b border-border/80 last:border-0 ${!admin.is_active ? "opacity-60 grayscale-[50%]" : ""}`}>
                          <td className="px-4 py-3 font-medium text-foreground">
                            {admin.full_name}
                            {!admin.is_active && (
                                <span className="ml-2 inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-500 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400">
                                    Disabled
                                </span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-muted-foreground">{admin.email}</td>
                          <td className="px-4 py-3 text-muted-foreground">{admin.phone_number || "—"}</td>
                          <td className="px-4 py-3 text-right">
                            {admin.is_active ? (
                                <button
                                  type="button"
                                  onClick={async () => {
                                      setAdminToDelete({id: admin.user_id, name: admin.full_name})
                                      setLoadingTasks(true)
                                      setPendingTasks(null)
                                      try {
                                          const res = await apiFetch(`/users/${admin.user_id}/pending-tasks`)
                                          setPendingTasks((res as any).tasks || [])
                                      } catch(e) {
                                          console.error(e)
                                          setPendingTasks([])
                                      } finally {
                                          setLoadingTasks(false)
                                      }
                                  }}
                                  disabled={superAdminsLoading}
                                  className="text-xs font-medium text-destructive hover:underline disabled:opacity-50"
                                >
                                  Deactivate
                                </button>
                            ) : (
                                <button
                                  type="button"
                                  onClick={async () => {
                                      if (!selectedOrgId) return
                                      setSuperAdminsLoading(true)
                                      try {
                                          await organizationsApi.reactivateSuperAdmin(selectedOrgId, admin.user_id)
                                          setSuperAdmins((current) =>
                                              current.map((a) =>
                                                  a.user_id === admin.user_id ? { ...a, is_active: true } : a
                                              ).sort((a, b) => {
                                                  if (a.is_active && !b.is_active) return -1;
                                                  if (!a.is_active && b.is_active) return 1;
                                                  return a.full_name.localeCompare(b.full_name);
                                              })
                                          )
                                      } catch (e: unknown) {
                                          setSuperAdminsError(getErrorMessage(e, "We couldn't reactivate the super admin."))
                                      } finally {
                                          setSuperAdminsLoading(false)
                                      }
                                  }}
                                  disabled={superAdminsLoading}
                                  className="text-xs font-medium text-emerald-600 hover:underline disabled:opacity-50 dark:text-emerald-400"
                                >
                                  Reactivate
                                </button>
                            )}
                          </td>
                        </tr>
                        </React.Fragment>
                      )})
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Add Super Admin Form */}
            <div className="mt-6 border-t border-border pt-6">
              <h3 className="text-sm font-semibold text-foreground mb-3">Add Super Admin</h3>
              <form onSubmit={handleCreateSuperAdmin} className="space-y-4">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <label className="text-sm text-foreground">
                    Name
                    <input
                      className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      value={newAdminName}
                      onChange={(e) => setNewAdminName(e.target.value)}
                      required
                      disabled={newAdminBusy}
                    />
                  </label>
                  <label className="text-sm text-foreground">
                    Email
                    <input
                      type="email"
                      className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      value={newAdminEmail}
                      onChange={(e) => setNewAdminEmail(e.target.value)}
                      required
                      disabled={newAdminBusy}
                    />
                  </label>
                  <label className="text-sm text-foreground">
                    Temporary Password
                    <input
                      type="password"
                      className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      value={newAdminPassword}
                      onChange={(e) => setNewAdminPassword(e.target.value)}
                      required
                      disabled={newAdminBusy}
                    />
                    {newAdminPassword.length > 0 && (
                      <PasswordValidation password={newAdminPassword} />
                    )}
                  </label>
                  <label className="text-sm text-foreground">
                    Phone (optional)
                    <input
                      className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      value={newAdminPhone}
                      onChange={(e) => setNewAdminPhone(e.target.value)}
                      maxLength={20}
                      disabled={newAdminBusy}
                    />
                  </label>
                </div>
                
                {newAdminError ? (
                  <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                    {newAdminError}
                  </div>
                ) : null}

                <div className="flex justify-end">
                  <button
                    type="submit"
                    disabled={newAdminBusy}
                    className="rounded-md border border-input bg-background px-4 py-2 text-sm font-medium text-foreground hover:bg-accent disabled:opacity-60"
                  >
                    {newAdminBusy ? "Adding..." : "Add Super Admin"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>

      {/* Modals */}
      <ConfirmationModal
        isOpen={showCreateAdminWarning}
        title="Create Super Admin"
        message="You are about to create a new Super Admin for this organization. This user will have full access to manage the tenant. Are you sure you want to proceed?"
        confirmText="Yes, create"
        cancelText="Cancel"
        isDanger={true}
        onCancel={() => setShowCreateAdminWarning(false)}
        onConfirm={proceedWithCreateAdmin}
      />

      <ConfirmationModal
        isOpen={!!adminToDelete && !loadingTasks && (!pendingTasks || pendingTasks.length === 0)}
        title="Deactivate Super Admin"
        message={`Are you sure you want to deactivate ${adminToDelete?.name}? They will lose access to the platform, but their role will be preserved.`}
        confirmText={superAdminsLoading ? "Deactivating..." : "Deactivate"}
        cancelText="Cancel"
        isDanger={true}
        onCancel={() => {
            setAdminToDelete(null)
            setPendingTasks(null)
        }}
        onConfirm={() => {
            if (adminToDelete) {
                void handleDeleteSuperAdmin(adminToDelete.id)
            }
        }}
      />

      <ConfirmationModal
        isOpen={!!adminToDelete && !loadingTasks && (pendingTasks !== null && pendingTasks.length > 0)}
        title="Cannot Deactivate Super Admin"
        message={
            <div className="space-y-3">
                <p>This super admin cannot be deactivated because they have pending tasks.</p>
                <div className="max-h-40 overflow-y-auto rounded-md border border-destructive/20 bg-destructive/5 p-2 text-sm text-destructive">
                    <ul className="list-inside list-disc">
                        {pendingTasks?.map((task) => (
                            <li key={task.id}>
                                <strong>{task.document_name}</strong> - {task.stage}
                            </li>
                        ))}
                    </ul>
                </div>
                <p>Please reassign or complete these tasks first.</p>
            </div>
        }
        confirmText="Got it"
        cancelText="Cancel"
        isDanger={true}
        onCancel={() => {
            setAdminToDelete(null)
            setPendingTasks(null)
        }}
        onConfirm={() => {
            setAdminToDelete(null)
            setPendingTasks(null)
        }}
      />
    </MainLayout>
  )
}
