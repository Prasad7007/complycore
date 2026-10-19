import * as React from "react"
import { Link } from "react-router-dom"

import { MainLayout } from "@/components/layout/MainLayout"
import { organizationsApi } from "@/lib/api"
import { PasswordValidation } from "@/components/auth/PasswordValidation"
import { ConfirmationModal } from "@/components/models/ConfirmationModal"

const BYTES_PER_GIB = 1024 * 1024 * 1024

function bytesToGiBString(bytes: number) {
  return (bytes / BYTES_PER_GIB).toFixed(2)
}

type BootstrapResult = {
  organization_id: string
  organization_slug: string
  superadmin_user_id: string
  superadmin_email: string
  message: string
}

export default function OwnerMultitenancyPage() {
  const [organizationName, setOrganizationName] = React.useState("")
  const [organizationSlug, setOrganizationSlug] = React.useState("")
  const [superAdminName, setSuperAdminName] = React.useState("")
  const [superAdminEmail, setSuperAdminEmail] = React.useState("")
  const [superAdminPassword, setSuperAdminPassword] = React.useState("")
  const [superAdminDepartment, setSuperAdminDepartment] = React.useState("Super Admin")
  const [superAdminPhone, setSuperAdminPhone] = React.useState("")
  const [departmentOptions, setDepartmentOptions] = React.useState<string[]>([])
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [result, setResult] = React.useState<BootstrapResult | null>(null)
  const [showConfirmation, setShowConfirmation] = React.useState(false)

  React.useEffect(() => {
    const load = async () => {
      try {
        const depts = await organizationsApi.listDepartments()
        setDepartmentOptions(Array.isArray(depts) ? depts : [])
      } catch {
        setDepartmentOptions([])
      }
    }
    void load()
  }, [])

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setShowConfirmation(true)
  }

  const proceedWithSubmit = async () => {
    setBusy(true)
    setError(null)
    setResult(null)
    setShowConfirmation(false)
    try {
      const res = await organizationsApi.bootstrap({
        organization_name: organizationName,
        organization_slug: organizationSlug,
        superadmin_full_name: superAdminName,
        superadmin_email: superAdminEmail,
        superadmin_password: superAdminPassword,
        superadmin_department: superAdminDepartment,
        superadmin_phone: superAdminPhone.trim() || undefined,
      })
      setResult(res)
    } catch (err: unknown) {
      let msg = "We couldn't create the organization. Please try again."
      if (err instanceof Error) {
        const lower = err.message.toLowerCase()
        if (lower.includes("fetch") || lower.includes("network")) {
          msg = "Network error. Please check your connection and try again."
        } else if (lower.includes("internal server error") || lower.includes("500")) {
          msg = "Something went wrong on our servers. Please try again later."
        } else if (err.message) {
          msg = err.message
        }
      }
      setError(msg)
    } finally {
      setBusy(false)
    }
  }

  return (
    <MainLayout
      header={{
        breadcrumbs: [
          { label: "Owner", to: "/owner/multitenancy" },
          { label: "Create organization" },
        ],
      }}
    >
      <div className="mx-auto w-full max-w-4xl space-y-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-lg font-bold text-foreground">Owner Multitenancy Operations</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Create tenant organizations. Each new org starts with quota enabled, a rollout date of today, and defaults of 50 uploads / {bytesToGiBString(2 * BYTES_PER_GIB)} GiB.
            </p>
          </div>
          <Link
            to="/owner/organizations"
            className="inline-flex h-9 shrink-0 items-center justify-center rounded-md border border-input bg-background px-3 text-sm font-medium text-foreground hover:bg-accent"
          >
            View all organizations
          </Link>
        </div>

        <form onSubmit={onSubmit} className="space-y-4 rounded-xl border border-border bg-card p-5">
          <div>
            <h2 className="text-base font-semibold text-foreground">Create Organization</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Provision a tenant organization and its first super admin.
            </p>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <label className="text-sm text-foreground">
              Organization Name
              <input
                className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={organizationName}
                onChange={(e) => setOrganizationName(e.target.value)}
                required
              />
            </label>
            <label className="text-sm text-foreground">
              Organization Slug
              <input
                className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={organizationSlug}
                onChange={(e) => setOrganizationSlug(e.target.value)}
                required
              />
            </label>
            <label className="text-sm text-foreground">
              Super Admin Name
              <input
                className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={superAdminName}
                onChange={(e) => setSuperAdminName(e.target.value)}
                required
              />
            </label>
            <label className="text-sm text-foreground">
              Super Admin Email
              <input
                type="email"
                className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={superAdminEmail}
                onChange={(e) => setSuperAdminEmail(e.target.value)}
                required
              />
            </label>
            <label className="text-sm text-foreground">
              Temporary Password
              <input
                type="password"
                className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={superAdminPassword}
                onChange={(e) => setSuperAdminPassword(e.target.value)}
                required
              />
              {superAdminPassword.length > 0 && (
                <PasswordValidation password={superAdminPassword} />
              )}
            </label>
            <label className="text-sm text-foreground">
              Department
              <input
                className="mt-1 h-10 w-full rounded-md border border-input bg-muted px-3 text-sm"
                value={superAdminDepartment}
                disabled
              />
            </label>
            <label className="text-sm text-foreground md:col-span-2">
              Phone (optional, max 20 characters)
              <input
                className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={superAdminPhone}
                maxLength={20}
                onChange={(e) => setSuperAdminPhone(e.target.value)}
              />
            </label>
          </div>

          {error ? (
            <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          ) : null}
          {result ? (
            <div className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">
              {result.message} Org: <strong>{result.organization_slug}</strong>, Super Admin:{" "}
              <strong>{result.superadmin_email}</strong>
            </div>
          ) : null}

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={busy}
              className="rounded-md bg-gradient-to-r from-[#128ADA] to-[#662CC4] px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {busy ? "Creating..." : "Create Organization"}
            </button>
          </div>
        </form>

        <div className="space-y-3 rounded-xl border border-border bg-card p-5">
          <div>
            <h2 className="text-base font-semibold text-foreground">Default Upload Quota</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              New organizations are initialized with the platform v1 defaults below. Use the Organizations page if you want to delay rollout or change limits for a specific client.
            </p>
          </div>
          <div className="rounded-md border border-border/70 bg-muted/30 px-3 py-3 text-sm text-muted-foreground">
            <p>
              <strong className="text-foreground">Quota enforcement:</strong> Enabled by default
            </p>
            <p className="mt-1">
              <strong className="text-foreground">Default limits:</strong> 50 uploads / {bytesToGiBString(2 * BYTES_PER_GIB)} GiB
            </p>
            <p className="mt-1">
              <strong className="text-foreground">Default rollout:</strong> Org creation date (today when the owner creates the org)
            </p>
          </div>
        </div>
      </div>

      <ConfirmationModal
        isOpen={showConfirmation}
        title="Create Organization & Super Admin"
        message={`You are about to create the organization "${organizationName}" and provision a new Super Admin account for ${superAdminEmail}. This user will have full administrative access to this new tenant. Are you sure you want to proceed?`}
        confirmText="Yes, create"
        cancelText="Cancel"
        isDanger={true}
        onCancel={() => setShowConfirmation(false)}
        onConfirm={proceedWithSubmit}
      />
    </MainLayout>
  )
}
