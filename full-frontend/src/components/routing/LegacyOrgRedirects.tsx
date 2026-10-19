import * as React from "react"
import { useLocation, useNavigate, useParams } from "react-router-dom"

import { fetchUserMeFresh } from "@/lib/api"

type MeOrg = { organization?: { slug?: string } | null }

function useRedirectToTenantPath(suffix: string) {
  const navigate = useNavigate()
  React.useEffect(() => {
    let cancelled = false
    void fetchUserMeFresh<MeOrg>()
      .then((me) => {
        if (cancelled) return
        const slug = me?.organization?.slug
        if (slug) {
          navigate(`/orgs/${encodeURIComponent(String(slug))}/${suffix}`, { replace: true })
        } else {
          navigate("/pending-access", { replace: true })
        }
      })
      .catch(() => {
        if (!cancelled) navigate("/login", { replace: true })
      })
    return () => {
      cancelled = true
    }
  }, [navigate, suffix])
}

/** Redirect legacy `/dashboard/default` → `/orgs/{me.organization.slug}/dashboard/default`. */
export function LegacyDashboardDefaultRedirect() {
  useRedirectToTenantPath("dashboard/default")
  return (
    <div className="flex min-h-[30vh] items-center justify-center text-sm text-muted-foreground">
      Redirecting…
    </div>
  )
}

export function LegacyValidateDocumentsRedirect() {
  useRedirectToTenantPath("validate-documents")
  return (
    <div className="flex min-h-[30vh] items-center justify-center text-sm text-muted-foreground">
      Redirecting…
    </div>
  )
}

export function LegacyValidateDocumentDetailRedirect() {
  const { docId } = useParams<{ docId: string }>()
  const navigate = useNavigate()
  React.useEffect(() => {
    let cancelled = false
    void fetchUserMeFresh<MeOrg>()
      .then((me) => {
        if (cancelled) return
        const slug = me?.organization?.slug
        if (slug && docId) {
          navigate(
            `/orgs/${encodeURIComponent(String(slug))}/validate-documents/detail/${encodeURIComponent(docId)}`,
            { replace: true }
          )
        } else {
          navigate("/pending-access", { replace: true })
        }
      })
      .catch(() => {
        if (!cancelled) navigate("/login", { replace: true })
      })
    return () => {
      cancelled = true
    }
  }, [navigate, docId])
  return (
    <div className="flex min-h-[30vh] items-center justify-center text-sm text-muted-foreground">
      Redirecting…
    </div>
  )
}

export function LegacyUploadDocumentRedirect() {
  const navigate = useNavigate()
  const { search } = useLocation()
  React.useEffect(() => {
    let cancelled = false
    void fetchUserMeFresh<MeOrg>()
      .then((me) => {
        if (cancelled) return
        const slug = me?.organization?.slug
        if (slug) {
          navigate(
            `/orgs/${encodeURIComponent(String(slug))}/upload-document${search || ""}`,
            { replace: true }
          )
        } else {
          navigate("/pending-access", { replace: true })
        }
      })
      .catch(() => {
        if (!cancelled) navigate("/login", { replace: true })
      })
    return () => {
      cancelled = true
    }
  }, [navigate, search])
  return (
    <div className="flex min-h-[30vh] items-center justify-center text-sm text-muted-foreground">
      Redirecting…
    </div>
  )
}

export function LegacyPublishedDocumentsRedirect() {
  useRedirectToTenantPath("published-documents")
  return (
    <div className="flex min-h-[30vh] items-center justify-center text-sm text-muted-foreground">
      Redirecting…
    </div>
  )
}

export function LegacyReportsRedirect() {
  useRedirectToTenantPath("reports")
  return (
    <div className="flex min-h-[30vh] items-center justify-center text-sm text-muted-foreground">
      Redirecting…
    </div>
  )
}

export function LegacyReportDetailRedirect() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  React.useEffect(() => {
    let cancelled = false
    void fetchUserMeFresh<MeOrg>()
      .then((me) => {
        if (cancelled) return
        const slug = me?.organization?.slug
        if (slug && id) {
          navigate(`/orgs/${encodeURIComponent(String(slug))}/reports/${encodeURIComponent(id)}`, {
            replace: true,
          })
        } else {
          navigate("/pending-access", { replace: true })
        }
      })
      .catch(() => {
        if (!cancelled) navigate("/login", { replace: true })
      })
    return () => {
      cancelled = true
    }
  }, [navigate, id])
  return (
    <div className="flex min-h-[30vh] items-center justify-center text-sm text-muted-foreground">
      Redirecting…
    </div>
  )
}

export function LegacyAuditTrailRedirect() {
  useRedirectToTenantPath("audit-trail")
  return (
    <div className="flex min-h-[30vh] items-center justify-center text-sm text-muted-foreground">
      Redirecting…
    </div>
  )
}

