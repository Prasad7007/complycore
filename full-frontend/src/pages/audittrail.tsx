import * as React from "react"
import { createPortal } from "react-dom"
import { Navigate, useParams, useSearchParams, NavLink, useNavigate } from "react-router-dom"
import { Calendar, ChevronDown, Eye, X, FileText } from "lucide-react"
import { FileIcon } from "@/components/icons/FileIcon"

import { MainLayout } from "@/components/layout/MainLayout"
import { DocumentPreviewCard } from "@/components/layout/document-preview-card"
import { AuditTrailExpandedPanel } from "@/components/layout/audit-trail-expanded-panel"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { auditApi, documentsApi, reportsApi, type AuditTrailRow, type ComplianceReportRow, type ReviewVersion } from "@/lib/api"
import { downloadReportPdf, openReportPdfInNewTab } from "@/lib/report-export"
import { loadComplianceReportExportPayload } from "@/lib/compliance-report-export-data"
import { computeLineDiff, type DiffLine } from "@/lib/diff"
import { cn } from "@/lib/utils"

type AuditRow = AuditTrailRow

function Avatar({ name, size = 22 }: { name: string; size?: number }) {
  const initials = name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("")
  return (
    <div
      className="grid shrink-0 place-items-center rounded-full bg-foreground/10 text-[10px] font-semibold text-foreground"
      style={{ width: size, height: size }}
      aria-hidden
    >
      {initials || "U"}
    </div>
  )
}


const STAGE_LABELS: Record<string, string> = {
  sme_review: "SME Review",
  marketing_review: "Marketing Review",
  compliance_review: "Compliance Review",
  needs_revision: "Needs Revision",
  publish: "Approved",
  approved: "Approved",
  published: "Published",
  rejected: "Rejected",
  document_upload: "Upload",
  skipped: "Out of Scope",
}

function StatusPill({ label }: { label: string }) {
  const displayLabel = STAGE_LABELS[label] || label
  const style =
    displayLabel === "Compliance Review"
      ? "border-orange-200 bg-orange-50 text-orange-700 dark:bg-orange-950/30 dark:text-orange-400"
      : displayLabel === "Published"
        ? "border-teal-200 bg-teal-50 text-teal-700 dark:bg-teal-950/30 dark:text-teal-400"
        : displayLabel === "Rejected"
          ? "border-red-200 bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-400"
          : displayLabel === "Approved"
            ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-400"
            : displayLabel === "SME Review"
              ? "border-purple-200 bg-purple-50 text-purple-700 dark:bg-purple-950/30 dark:text-purple-400"
              : displayLabel === "Marketing Review"
                ? "border-blue-200 bg-blue-50 text-blue-700 dark:bg-blue-950/30 dark:text-blue-400"
                : displayLabel === "Needs Revision"
                  ? "border-yellow-200 bg-yellow-50 text-yellow-700 dark:bg-yellow-950/30 dark:text-yellow-400"
                  : displayLabel === "Out of Scope"
                    ? "border-slate-300 bg-slate-100 text-slate-700 dark:bg-slate-800/40 dark:text-slate-400"
                    : "border-foreground/15 bg-muted/40 text-foreground/60"
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium", style)}>
      {displayLabel}
    </span>
  )
}

function SelectField({
  id,
  value,
  onChange,
  options,
  placeholder = "Select",
}: {
  id: string
  value: string
  onChange: (v: string) => void
  options: { label: string; value: string }[]
  placeholder?: string
}) {
  return (
    <div className="relative">
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 w-full appearance-none rounded-md border border-input bg-background px-3 pr-9 text-sm text-foreground shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <option value="">{placeholder}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value} className="bg-background">
            {o.label}
          </option>
        ))}
      </select>
      <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 flex flex-col items-center gap-[2px] text-muted-foreground">
        <svg width="8" height="5" viewBox="0 0 8 5" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden>
          <path d="M1 4L4 1L7 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <svg width="8" height="5" viewBox="0 0 8 5" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden>
          <path d="M1 1L4 4L7 1" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </span>
    </div>
  )
}

export default function AuditTrailPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const initialReviewId = searchParams.get("reviewId") || ""
  const [headerSearch, setHeaderSearch] = React.useState("")
  const [docId, setDocId] = React.useState(initialReviewId)
  const [docName, setDocName] = React.useState("")
  const [status, setStatus] = React.useState("")
  const [department, setDepartment] = React.useState("")
  const [role, setRole] = React.useState("")
  const [dateFrom, setDateFrom] = React.useState("")
  const [dateTo, setDateTo] = React.useState("")
  const [dateFromFocused, setDateFromFocused] = React.useState(false)
  const [dateToFocused, setDateToFocused] = React.useState(false)

  const [applied, setApplied] = React.useState({
    docId: initialReviewId,
    docName: "",
    status: "",
    department: "",
    role: "",
    dateFrom: "",
    dateTo: "",
  })

  const [openReviewId, setOpenReviewId] = React.useState<string | null>(null)
  const [previewOpen, setPreviewOpen] = React.useState(false)

  const [rows, setRows] = React.useState<AuditRow[]>([])
  const [loading, setLoading] = React.useState(true)
  const [reportsByReviewId, setReportsByReviewId] = React.useState<Record<string, ComplianceReportRow>>({})
  const [exportingReviewId, setExportingReviewId] = React.useState<string | null>(null)
  const [versionsByReview, setVersionsByReview] = React.useState<Record<string, ReviewVersion[]>>({})
  const [versionsLoadingByReview, setVersionsLoadingByReview] = React.useState<Record<string, boolean>>({})
  const [selectedVersionByReview, setSelectedVersionByReview] = React.useState<Record<string, string>>({})
  const [compareOpen, setCompareOpen] = React.useState(false)
  const [compareReviewId, setCompareReviewId] = React.useState<string | null>(null)
  const [compareLeftVersionId, setCompareLeftVersionId] = React.useState<string>("")
  const [compareRightVersionId, setCompareRightVersionId] = React.useState<string>("")
  const [previewReviewId, setPreviewReviewId] = React.useState<string | null>(null)
  const [previewFile, setPreviewFile] = React.useState<{
    url: string
    mime: string
    fileName: string
    originalUrl?: string
    originalFileName?: string
  } | null>(null)
  const [previewFileLoading, setPreviewFileLoading] = React.useState(false)
  const [previewFileError, setPreviewFileError] = React.useState<string | null>(null)

  React.useEffect(() => {
    async function fetchAuditTrail() {
      if (!orgSlug?.trim()) {
        setLoading(false)
        return
      }
      try {
        setLoading(true)
        const [data, reports] = await Promise.all([
          auditApi.getGlobalAuditTrail(orgSlug),
          reportsApi.list(orgSlug).catch(() => []),
        ])
        setRows(data)
        const reportMap: Record<string, ComplianceReportRow> = {}
        reports.forEach((r) => {
          if (r.review_id) reportMap[r.review_id] = r
        })
        setReportsByReviewId(reportMap)

        const queryReviewId = searchParams.get("reviewId")
        if (queryReviewId && data.some((d) => d.reviewId === queryReviewId)) {
          setOpenReviewId(queryReviewId)
          // Fetch version list inline to populate expanded row details immediately without triggering dependency loops
          setVersionsLoadingByReview((prev) => ({ ...prev, [queryReviewId]: true }))
          auditApi.getReviewVersions(orgSlug, queryReviewId)
            .then((res) => {
              const versions = res.versions || []
              setVersionsByReview((prev) => ({ ...prev, [queryReviewId]: versions }))
              if (versions.length > 0) {
                setSelectedVersionByReview((prev) =>
                  prev[queryReviewId] ? prev : { ...prev, [queryReviewId]: versions[0].id }
                )
              }
            })
            .catch((err) => {
              console.error("Failed to pre-fetch versions for queryReviewId:", err)
              setVersionsByReview((prev) => ({ ...prev, [queryReviewId]: [] }))
            })
            .finally(() => {
              setVersionsLoadingByReview((prev) => ({ ...prev, [queryReviewId]: false }))
            })
        }
      } catch (error) {
        console.error("Failed to fetch audit trail:", error)
      } finally {
        setLoading(false)
      }
    }
    fetchAuditTrail()
  }, [searchParams, orgSlug])

  const resolveReportForReview = React.useCallback(
    async (reviewId: string) => {
      if (!reviewId || !orgSlug?.trim()) return null
      let report = reportsByReviewId[reviewId]
      if (!report) {
        const docs = await reportsApi.list(orgSlug)
        report = (docs.find((r) => r.review_id === reviewId) as ComplianceReportRow) || null
        if (report) setReportsByReviewId((prev) => ({ ...prev, [reviewId]: report }))
      }
      return report
    },
    [reportsByReviewId, orgSlug]
  )

  const handleDownloadReport = React.useCallback(
    async (reviewId: string) => {
      if (!orgSlug?.trim()) return
      setExportingReviewId(reviewId)
      try {
        const report = await resolveReportForReview(reviewId)
        if (!report) {
          alert("Report not found for this review.")
          return
        }
        const { findings, auditEvents } = await loadComplianceReportExportPayload(orgSlug, reviewId)
        downloadReportPdf(report, findings, auditEvents)
      } catch (error) {
        console.error("Download report failed", error)
        alert("Failed to download report.")
      } finally {
        setExportingReviewId(null)
      }
    },
    [resolveReportForReview, orgSlug]
  )

  const handleViewReport = React.useCallback(
    async (reviewId: string) => {
      if (!orgSlug?.trim()) return
      // Open the window immediately within the user-triggered click handler
      // to prevent popup blockers from catching it later after async calls.
      const win = window.open("about:blank", "_blank")
      if (win) {
        win.document.title = "Loading Report..."
        // Basic loading message in the new tab
        win.document.body.innerHTML = `
          <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; font-family:sans-serif; color:#666;">
            <div style="border:4px solid #f3f3f3; border-top:4px solid #128BDA; border-radius:50%; width:30px; height:30px; animation:spin 1s linear infinite;"></div>
            <p style="margin-top:16px;">Generating Compliance Report...</p>
            <style>@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }</style>
          </div>
        `
      }

      try {
        const report = await resolveReportForReview(reviewId)
        if (!report) {
          if (win) win.close()
          alert("Report not found for this review.")
          return
        }
        const { findings, auditEvents } = await loadComplianceReportExportPayload(orgSlug, reviewId)
        const opened = openReportPdfInNewTab(report, findings, auditEvents, win)
        if (!opened) {
          if (win) win.close()
          alert("Report preview was blocked by your browser. Please allow popups for this site to use View.")
        }
      } catch (error) {
        console.error("Open report failed", error)
        if (win) win.close()
        alert("Failed to generate report preview.")
      }
    },
    [resolveReportForReview, orgSlug]
  )

  const fetchVersionsForReview = React.useCallback(async (reviewId: string) => {
    if (!orgSlug?.trim() || !reviewId || versionsByReview[reviewId] || versionsLoadingByReview[reviewId]) return
    setVersionsLoadingByReview((prev) => ({ ...prev, [reviewId]: true }))
    try {
      const res = await auditApi.getReviewVersions(orgSlug, reviewId)
      const versions = res.versions || []
      setVersionsByReview((prev) => ({ ...prev, [reviewId]: versions }))
      if (versions.length > 0) {
        setSelectedVersionByReview((prev) =>
          prev[reviewId] ? prev : { ...prev, [reviewId]: versions[0].id }
        )
      }
    } catch (error) {
      console.error("Failed to fetch versions:", error)
      setVersionsByReview((prev) => ({ ...prev, [reviewId]: [] }))
    } finally {
      setVersionsLoadingByReview((prev) => ({ ...prev, [reviewId]: false }))
    }
  }, [orgSlug, versionsByReview, versionsLoadingByReview])

  const openCompareForReview = React.useCallback((reviewId: string) => {
    const versions = versionsByReview[reviewId] || []
    if (versions.length < 2) return
    setCompareReviewId(reviewId)
    setCompareLeftVersionId(versions[0].id)
    setCompareRightVersionId(versions[1].id)
    setCompareOpen(true)
  }, [versionsByReview])

  const compareVersions = React.useMemo(() => {
    if (!compareReviewId) return { left: null, right: null }
    const versions = versionsByReview[compareReviewId] || []
    const left = versions.find((v) => v.id === compareLeftVersionId) || null
    const right = versions.find((v) => v.id === compareRightVersionId) || null
    return { left, right }
  }, [compareLeftVersionId, compareReviewId, compareRightVersionId, versionsByReview])

  const summarizeTextDelta = React.useCallback((leftText?: string, rightText?: string) => {
    const oldLen = (leftText || "").length
    const newLen = (rightText || "").length
    const diff = newLen - oldLen
    return {
      oldChars: oldLen,
      newChars: newLen,
      deltaChars: diff,
    }
  }, [])

  React.useEffect(() => {
    if (!previewOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setPreviewOpen(false)
        setPreviewReviewId(null)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [previewOpen])

  React.useEffect(() => {
    if (!previewOpen || !previewReviewId) {
      setPreviewFile(null)
      setPreviewFileError(null)
      setPreviewFileLoading(false)
      return
    }
    const versions = versionsByReview[previewReviewId] || []
    const vid = selectedVersionByReview[previewReviewId] || versions[0]?.id
    if (!vid) {
      if (!versionsLoadingByReview[previewReviewId]) {
        setPreviewFileLoading(false)
        setPreviewFileError("No document version available.")
        setPreviewFile(null)
      } else {
        setPreviewFileLoading(true)
        setPreviewFileError(null)
      }
      return
    }
    let cancelled = false
    setPreviewFileLoading(true)
    setPreviewFileError(null)
    documentsApi
      .getVersionFileUrl(orgSlug, vid)
      .then((res) => {
        if (cancelled) return
        setPreviewFile({
          url: res.url,
          mime: res.mime,
          fileName: res.file_name,
          originalUrl: res.original_url,
          originalFileName: res.original_file_name,
        })
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setPreviewFile(null)
        setPreviewFileError(e instanceof Error ? e.message : "Failed to load document from storage.")
      })
      .finally(() => {
        if (!cancelled) setPreviewFileLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [
    previewOpen,
    previewReviewId,
    versionsByReview,
    selectedVersionByReview,
    versionsLoadingByReview,
  ])

  const reviewStageOptions = React.useMemo(() => {
    const stages = Array.from(new Set(rows.map((r) => r.status))).filter(Boolean)
    return stages.map((s) => ({ label: STAGE_LABELS[s] || s, value: s })).sort((a, b) => a.label.localeCompare(b.label))
  }, [rows])

  const departmentOptions = React.useMemo(() => {
    const depts = Array.from(new Set(rows.map((r) => r.department))).filter(Boolean)
    return depts.map((d) => ({ label: d, value: d })).sort((a, b) => a.label.localeCompare(b.label))
  }, [rows])

  const roleOptions = React.useMemo(() => {
    return [
      { label: "Super Admin", value: "super_admin" },
      { label: "Marketing", value: "marketing" },
      { label: "SME Reviewer", value: "sme" },
      { label: "Compliance", value: "compliance" },
    ]
  }, [])

  // Filter rows by docId, docName, status, department, role and date range
  const filteredRows = React.useMemo(() => {
    const headerQ = headerSearch.trim().toLowerCase()
    const idQ = applied.docId.trim().toLowerCase()
    const nameQ = applied.docName.trim().toLowerCase()
    const statusQ = applied.status
    const deptQ = applied.department
    const roleQ = applied.role
    const fromQ = applied.dateFrom
    const toQ = applied.dateTo

    return rows.filter((r) => {
      if (
        headerQ &&
        !r.document?.toLowerCase().includes(headerQ) &&
        !r.reviewId?.toLowerCase().includes(headerQ) &&
        !r.step?.toLowerCase().includes(headerQ)
      ) {
        return false
      }
      if (idQ && !r.reviewId?.toLowerCase().includes(idQ) && !r.step?.toLowerCase().includes(idQ)) return false
      if (nameQ && !r.document?.toLowerCase().includes(nameQ)) return false
      if (statusQ && r.status !== statusQ) return false
      if (deptQ && r.department !== deptQ) return false
      if (roleQ && !r.roles?.includes(roleQ)) return false

      if (fromQ || toQ) {
        const utcTs = r.timestamp ? (r.timestamp.endsWith("Z") ? r.timestamp : r.timestamp + "Z") : null
        const ts = utcTs ? new Date(utcTs).getTime() : null
        if (fromQ && ts) {
          const fromTime = new Date(`${fromQ}T00:00:00`).getTime()
          if (ts < fromTime) return false
        }
        if (toQ && ts) {
          const toTime = new Date(`${toQ}T23:59:59.999`).getTime()
          if (ts > toTime) return false
        }
      }
      return true
    })
  }, [rows, applied, headerSearch])

  if (!orgSlug?.trim()) {
    return <Navigate to="/pending-access" replace />
  }

  return (
    <MainLayout
      header={{
        breadcrumbs: [
          { label: "ComplyCore", to: `/orgs/${encodeURIComponent(orgSlug)}/dashboard/default` },
          { label: "Audit Trail" },
        ],
        searchQuery: headerSearch,
        onSearchChange: setHeaderSearch,
        searchPlaceholder: "Search documents",
      }}
    >
      <div className="space-y-6">
        <div>
          <div className="text-lg font-bold text-foreground">Audit Trail</div>
          <div className="mt-0.5 text-sm text-muted-foreground">
            Immutable record of all compliance review activities and version history
          </div>
        </div>

        {/* Filters */}
        <Card className="rounded-xl border border-border bg-card shadow-sm dark:shadow-[-4px_4px_12px_rgba(0,0,0,0.3)]">
          <CardContent className="p-5">
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-8 items-end">
                <div className="space-y-2">
                  <Label className="text-xs font-semibold" htmlFor="docId">
                    Document ID
                  </Label>
                  <Input
                    id="docId"
                    value={docId}
                    onChange={(e) => setDocId(e.target.value)}
                    placeholder="Search ID"
                  />
                </div>

                <div className="space-y-2">
                  <Label className="text-xs font-semibold" htmlFor="docName">
                    Document Name
                  </Label>
                  <Input
                    id="docName"
                    value={docName}
                    onChange={(e) => setDocName(e.target.value)}
                    placeholder="Search name"
                  />
                </div>

                <div className="space-y-2">
                  <Label className="text-xs font-semibold" htmlFor="status">
                    Status
                  </Label>
                  <SelectField
                    id="status"
                    value={status}
                    onChange={setStatus}
                    options={reviewStageOptions}
                    placeholder="Select Status"
                  />
                </div>

                <div className="space-y-2">
                  <Label className="text-xs font-semibold" htmlFor="department">
                    Department
                  </Label>
                  <SelectField
                    id="department"
                    value={department}
                    onChange={setDepartment}
                    options={departmentOptions}
                    placeholder="Select Dept"
                  />
                </div>

                <div className="space-y-2">
                  <Label className="text-xs font-semibold" htmlFor="role">
                    Role
                  </Label>
                  <SelectField
                    id="role"
                    value={role}
                    onChange={setRole}
                    options={roleOptions}
                    placeholder="Select Role"
                  />
                </div>

                <div className="space-y-2">
                  <Label className="text-xs font-semibold" htmlFor="from">
                    Date From
                  </Label>
                  <div className="relative">
                    <Calendar className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    {!dateFrom && !dateFromFocused && (
                      <span className="pointer-events-none absolute left-9 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
                        From
                      </span>
                    )}
                    <Input
                      id="from"
                      type="date"
                      value={dateFrom}
                      onChange={(e) => setDateFrom(e.target.value)}
                      onMouseDown={(e) => {
                        const el = e.currentTarget as HTMLInputElement & { showPicker?: () => void }
                        if (el.showPicker) {
                          e.preventDefault()
                          el.focus()
                          el.showPicker()
                        }
                      }}
                      onFocus={(e) => {
                        setDateFromFocused(true)
                        ;(e.currentTarget as HTMLInputElement & { showPicker?: () => void }).showPicker?.()
                      }}
                      onBlur={() => setDateFromFocused(false)}
                      onKeyDown={(e) => {
                        if (e.key !== "Tab") e.preventDefault()
                      }}
                      className={cn(
                        "h-10 bg-background pl-9 appearance-none [&::-webkit-calendar-picker-indicator]:opacity-0 [&::-webkit-calendar-picker-indicator]:pointer-events-none",
                        !dateFrom && "text-transparent caret-transparent"
                      )}
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label className="text-xs font-semibold" htmlFor="to">
                    Date To
                  </Label>
                  <div className="relative">
                    <Calendar className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    {!dateTo && !dateToFocused && (
                      <span className="pointer-events-none absolute left-9 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
                        To
                      </span>
                    )}
                    <Input
                      id="to"
                      type="date"
                      value={dateTo}
                      onChange={(e) => setDateTo(e.target.value)}
                      onMouseDown={(e) => {
                        const el = e.currentTarget as HTMLInputElement & { showPicker?: () => void }
                        if (el.showPicker) {
                          e.preventDefault()
                          el.focus()
                          el.showPicker()
                        }
                      }}
                      onFocus={(e) => {
                        setDateToFocused(true)
                        ;(e.currentTarget as HTMLInputElement & { showPicker?: () => void }).showPicker?.()
                      }}
                      onBlur={() => setDateToFocused(false)}
                      onKeyDown={(e) => {
                        if (e.key !== "Tab") e.preventDefault()
                      }}
                      className={cn(
                        "h-10 bg-background pl-9 appearance-none [&::-webkit-calendar-picker-indicator]:opacity-0 [&::-webkit-calendar-picker-indicator]:pointer-events-none",
                        !dateTo && "text-transparent caret-transparent"
                      )}
                    />
                  </div>
                </div>

                <div>
                  <Button
                    className="w-full bg-[#128BDA] font-semibold text-white hover:bg-[#128BDA]/90"
                    onClick={() => setApplied({ docId, docName, status, department, role, dateFrom, dateTo })}
                  >
                    Apply
                  </Button>
                </div>
              </div>

              {/* Clear + count */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {(docId || docName || status || department || role || dateFrom || dateTo) && (
                    <button
                      type="button"
                      className="text-xs text-muted-foreground underline hover:text-foreground"
                      onClick={() => {
                        setDocId("")
                        setDocName("")
                        setStatus("")
                        setDepartment("")
                        setRole("")
                        setDateFrom("")
                        setDateTo("")
                        setApplied({ docId: "", docName: "", status: "", department: "", role: "", dateFrom: "", dateTo: "" })
                      }}
                    >
                      Clear filters
                    </button>
                  )}
                </div>
                {!loading && (applied.docId || applied.docName || applied.status || applied.department || applied.role || applied.dateFrom || applied.dateTo) && (
                  <span className="text-xs text-muted-foreground">
                    {filteredRows.length} of {rows.length} results
                  </span>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Table */}
        <Card className="rounded-xl border border-border bg-card shadow-sm dark:shadow-[-4px_4px_12px_rgba(0,0,0,0.3)]">
          <CardContent className="p-0">
            {/* overflow-x-auto keeps columns perfectly aligned when sidebar is open */}
            <div className="overflow-x-auto px-4 py-4">
              <table
                className="w-full min-w-[960px]"
                style={{ borderCollapse: "separate", borderSpacing: 0 }}
              >
                <thead>
                  <tr className="text-xs font-semibold uppercase tracking-wide text-foreground/40">
                    <th className="w-10 border-b border-r border-foreground/8 pb-3 text-center font-medium" />
                    <th className="w-14 border-b border-r border-foreground/8 pb-3 text-center font-medium">Id</th>
                    <th className="border-b border-r border-foreground/8 pb-3 pl-3 text-left font-medium">Document</th>
                    <th className="border-b border-r border-foreground/8 pb-3 text-center font-medium whitespace-nowrap">Status</th>
                    <th className="border-b border-r border-foreground/8 pb-3 text-center font-medium whitespace-nowrap">Date</th>
                    <th className="border-b border-r border-foreground/8 pb-3 text-center font-medium whitespace-nowrap">Performed By</th>
                    <th className="border-b border-r border-foreground/8 pb-3 text-center font-medium whitespace-nowrap">Version</th>
                    <th className="border-b border-r border-foreground/8 pb-3 text-center font-medium">Report</th>
                    <th className="border-b border-foreground/8 pb-3 text-center font-medium">Detail</th>
                  </tr>
                </thead>

                <tbody>
                  {/* Gap between header and first row */}
                  <tr aria-hidden><td colSpan={9} className="h-3 p-0" /></tr>
                  
                  {loading ? (
                    <tr>
                      <td colSpan={9} className="py-12 text-center">
                        <div className="flex flex-col items-center gap-2">
                          <div className="h-8 w-8 animate-spin rounded-full border-2 border-foreground/10 border-t-[#128BDA]" />
                          <span className="text-sm text-muted-foreground">Loading audit trail…</span>
                        </div>
                      </td>
                    </tr>
                  ) : filteredRows.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="py-12 text-center">
                        <div className="flex flex-col items-center gap-2">
                          <FileText className="h-8 w-8 text-muted-foreground/40" />
                          <span className="text-sm font-medium text-foreground">
                            {rows.length === 0 ? "No audit records yet" : "No results match your filters"}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {rows.length === 0
                              ? "Audit events will appear once documents are reviewed"
                              : "Try adjusting your search or date range"}
                          </span>
                        </div>
                      </td>
                    </tr>
                  ) : filteredRows.map((r) => {
                    const isOpen = openReviewId === r.reviewId
                    const reviewVersions = versionsByReview[r.reviewId] || []
                    const versionsLoading = !!versionsLoadingByReview[r.reviewId]
                    const selectedVersionId = selectedVersionByReview[r.reviewId]
                    // Shared cell classes
                    const cellBase = "bg-muted/50 px-2 py-3 text-center align-middle"
                    const firstCell = cn(cellBase, isOpen ? "rounded-tl-xl" : "rounded-l-xl")
                    const lastCell = cn(cellBase, isOpen ? "rounded-tr-xl" : "rounded-r-xl")
                    const statusLower = String(r.status || "").toLowerCase()
                    // Per requirement: disable report download/view until the document is approved or published.
                    const allowReportActions = statusLower === "approved" || statusLower === "published"

                    return (
                      <React.Fragment key={r.reviewId}>
                        {/* Main row */}
                        <tr 
                          className="transition-colors hover:[&>td]:bg-muted/80"
                        >
                          {/* Toggle */}
                          <td className={firstCell}>
                            <div className="flex justify-center">
                              <button
                                type="button"
                                className={cn(
                                  "grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground",
                                  isOpen && "bg-accent text-foreground"
                                )}
                                aria-label={isOpen ? "Collapse row" : "Expand row"}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setOpenReviewId((v) => {
                                    const nextOpen = v === r.reviewId ? null : r.reviewId
                                    if (nextOpen === r.reviewId) {
                                      fetchVersionsForReview(r.reviewId)
                                    }
                                    return nextOpen
                                  })
                                }}
                              >
                                <ChevronDown className={cn("h-4 w-4 transition-transform", isOpen && "rotate-180")} />
                              </button>
                            </div>
                          </td>

                          {/* Id */}
                          <td className={cn(cellBase, "text-xs font-mono text-muted-foreground whitespace-nowrap")}>
                            {r.step}
                          </td>

                          {/* Document Name */}
                          <td
                            className={cn(cellBase, "text-left pl-3", r.documentId && "cursor-pointer")}
                            onClick={() => {
                              if (r.documentId) {
                                navigate(`/orgs/${encodeURIComponent(orgSlug)}/validate-documents/detail/${r.documentId}`)
                              }
                            }}
                          >
                            <div className="flex items-center gap-2">
                              <FileIcon className="h-4 w-4 shrink-0 text-blue-500/70" />
                              <span className={cn("text-xs font-medium text-foreground leading-snug", r.documentId && "hover:underline")}>
                                {r.document}
                              </span>
                            </div>
                          </td>

                          {/* Status */}
                          <td className={cellBase}>
                            <div className="flex justify-center">
                              <StatusPill label={r.status} />
                            </div>
                          </td>

                          {/* Date */}
                          <td className={cn(cellBase, "text-xs text-muted-foreground whitespace-nowrap font-mono")}>
                            {r.timestamp ? new Date(r.timestamp.endsWith("Z") ? r.timestamp : r.timestamp + "Z").toLocaleDateString("en-US", { day: "2-digit", month: "short", year: "numeric" }) : "—"}
                          </td>

                          {/* Performed By */}
                          <td className={cellBase}>
                            <div className="flex flex-col items-center gap-1">
                              <Avatar name={r.performedBy} />
                              <span className="text-xs text-foreground leading-snug whitespace-nowrap">
                                {r.performedBy}
                              </span>
                            </div>
                          </td>

                          {/* Versions */}
                          <td className={cn(cellBase, "text-xs text-muted-foreground whitespace-nowrap")}>
                            {r.latestVersion || "-"}
                          </td>

                          {/* Reports */}
                          <td className={cellBase}>
                            <div className="flex items-center justify-center gap-2 text-muted-foreground">
                              <button
                                type="button"
                                className={cn(
                                  "grid h-8 w-8 place-items-center rounded-md hover:bg-accent hover:text-foreground",
                                  (!allowReportActions || exportingReviewId === r.reviewId) && "cursor-not-allowed opacity-50"
                                )}
                                aria-label="Download report"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  handleDownloadReport(r.reviewId)
                                }}
                                disabled={!allowReportActions || exportingReviewId === r.reviewId}
                              >
                                <img src="/shared/downloadIcon.svg" alt="download" className="h-4 w-4 dark:invert" />
                              </button>
                              <button
                                type="button"
                                className={cn(
                                  "grid h-8 w-8 place-items-center rounded-md hover:bg-accent hover:text-foreground",
                                  !allowReportActions && "cursor-not-allowed opacity-50"
                                )}
                                aria-label="View report"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  handleViewReport(r.reviewId)
                                }}
                                disabled={!allowReportActions}
                              >
                                <Eye className="h-4 w-4" />
                              </button>
                            </div>
                          </td>

                          {/* Details */}
                          <td className={lastCell}>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                setPreviewReviewId(r.reviewId)
                                setPreviewOpen(true)
                                fetchVersionsForReview(r.reviewId)
                              }}
                              className="text-xs font-medium text-foreground hover:underline"
                            >
                              View
                            </button>
                          </td>
                        </tr>

                        {/* Expanded panel — attached directly to the main row, no gap */}
                        {isOpen && (
                          <tr>
                            <td
                              colSpan={9}
                              className="rounded-b-xl bg-muted/40 px-3 pb-3 pt-0"
                            >
                              <div className="space-y-2">
                                {/* Version selector — ghost card, same style as sub-rows */}
                                <div className="flex flex-wrap items-center gap-2 rounded-xl bg-muted/50 px-3 py-2.5">
                                  {versionsLoading ? (
                                    <span className="text-xs text-muted-foreground">Loading versions...</span>
                                  ) : reviewVersions.length > 0 ? (
                                    reviewVersions.map((v, idx) => {
                                      const selected = selectedVersionId ? selectedVersionId === v.id : idx === 0
                                      return (
                                        <button
                                          key={v.id}
                                          type="button"
                                          onClick={() =>
                                            setSelectedVersionByReview((prev) => ({ ...prev, [r.reviewId]: v.id }))
                                          }
                                          className={cn(
                                            "rounded-lg px-3 py-1.5 text-xs font-semibold",
                                            selected
                                              ? "border border-foreground/10 bg-card shadow-sm"
                                              : "border border-foreground/15 bg-transparent text-muted-foreground hover:text-foreground"
                                          )}
                                        >
                                          {v.label}
                                          {idx === 0 ? (
                                            <span className="ml-1 font-medium text-emerald-600 dark:text-emerald-400">(Latest)</span>
                                          ) : null}
                                        </button>
                                      )
                                    })
                                  ) : (
                                    <span className="text-xs text-muted-foreground">No version history available.</span>
                                  )}
                                  <button
                                    type="button"
                                    disabled={reviewVersions.length < 2}
                                    onClick={() => openCompareForReview(r.reviewId)}
                                    className={cn(
                                      "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold",
                                      reviewVersions.length < 2
                                        ? "cursor-not-allowed bg-foreground/5 text-foreground/40"
                                        : "bg-foreground/10 text-foreground/70 hover:bg-foreground/15"
                                    )}
                                  >
                                    <img src="/audit-trail/Repeat.svg" alt="compare" className="h-3.5 w-3.5 dark:invert" />
                                    Compare Versions
                                  </button>
                                </div>

                                {/* Sub-workflow rows */}
                                {(() => {
                                  const currentReviewId = (versionsByReview[r.reviewId] || []).find(v => v.id === selectedVersionId)?.reviewId || r.reviewId
                                  return <AuditTrailExpandedPanel orgSlug={orgSlug} reviewId={currentReviewId} />
                                })()}
                              </div>
                            </td>
                          </tr>
                        )}

                        {/* Gap between card groups */}
                        <tr aria-hidden>
                          <td colSpan={9} className="h-3 p-0" />
                        </tr>
                      </React.Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>

      {compareOpen && compareReviewId && typeof document !== "undefined"
        ? createPortal(
            <div
              className="fixed inset-0 z-[9998] flex items-center justify-center bg-black/30 backdrop-blur-sm"
              role="dialog"
              aria-modal="true"
              aria-label="Compare versions"
              onMouseDown={(e) => {
                if (e.target === e.currentTarget) setCompareOpen(false)
              }}
            >
              <div className="w-[min(1100px,calc(100vw-32px))] rounded-xl border border-border bg-card p-4 shadow-xl dark:shadow-[0_24px_80px_rgba(0,0,0,0.45)]">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold text-foreground">Compare Versions</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setCompareOpen(false)}
                    className="grid h-9 w-9 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                    aria-label="Close compare"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>

                <div className="mb-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                  <div>
                    <Label className="text-xs font-semibold">Base Version</Label>
                    <select
                      value={compareLeftVersionId}
                      onChange={(e) => setCompareLeftVersionId(e.target.value)}
                      className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                    >
                      {(versionsByReview[compareReviewId] || []).map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <Label className="text-xs font-semibold">Compare With</Label>
                    <select
                      value={compareRightVersionId}
                      onChange={(e) => setCompareRightVersionId(e.target.value)}
                      className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                    >
                      {(versionsByReview[compareReviewId] || []).map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {compareVersions.left && compareVersions.right ? (
                  <>
                    <div className="mb-3 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
                      {(() => {
                        const delta = summarizeTextDelta(compareVersions.left?.text, compareVersions.right?.text)
                        const sign = delta.deltaChars >= 0 ? "+" : ""
                        return `Differences: ${delta.oldChars.toLocaleString()} → ${delta.newChars.toLocaleString()} chars (${sign}${delta.deltaChars.toLocaleString()})`
                      })()}
                    </div>
                    
                    {/* Git-style diff view */}
                    <div className="rounded-lg border bg-card overflow-hidden">
                      <div className="flex items-center justify-between border-b bg-muted/40 px-3 py-2">
                        <div>
                          <div className="text-xs text-muted-foreground">
                            {compareVersions.left.label} → {compareVersions.right.label}
                          </div>
                        </div>
                      </div>
                      
                      {(() => {
                        const diff = computeLineDiff(compareVersions.left?.text || "", compareVersions.right?.text || "")
                        
                        // Show at most 100 lines of diff
                        const displayDiff = diff.slice(0, 100)
                        const hasMore = diff.length > 100
                        
                        return (
                          <div className="max-h-[500px] overflow-y-auto font-mono text-xs">
                            {displayDiff.map((line: DiffLine, idx: number) => {
                              const bgColor = 
                                line.type === 'addition' ? 'bg-green-50 dark:bg-green-950/20' :
                                line.type === 'deletion' ? 'bg-red-50 dark:bg-red-950/20' :
                                'bg-transparent'
                              
                              const textColor = 
                                line.type === 'addition' ? 'text-green-700 dark:text-green-400' :
                                line.type === 'deletion' ? 'text-red-700 dark:text-red-400' :
                                'text-muted-foreground'
                              
                              const prefix = 
                                line.type === 'addition' ? '+' :
                                line.type === 'deletion' ? '-' :
                                ' '
                              
                              return (
                                <div key={idx} className={cn("px-3 py-1 border-b border-foreground/5", bgColor)}>
                                  <span className="mr-2 inline-block w-6 text-center text-muted-foreground/50">
                                    {line.lineNum && `${line.lineNum}`}
                                  </span>
                                  <span className={cn("font-semibold", textColor)}>{prefix}</span>
                                  <span className={cn("break-words", textColor)}>
                                    {line.content || <span className="text-muted-foreground/40 italic">(empty line)</span>}
                                  </span>
                                </div>
                              )
                            })}
                            
                            {hasMore && (
                              <div className="px-3 py-2 text-center text-xs text-muted-foreground bg-muted/20 border-t">
                                … and {diff.length - 100} more lines
                              </div>
                            )}
                          </div>
                        )
                      })()}
                    </div>
                  </>
                ) : (
                  <div className="py-8 text-center text-sm text-muted-foreground">
                    Select two versions to compare.
                  </div>
                )}
              </div>
            </div>,
            document.body
          )
        : null}

      {/* View modal (uses DocumentPreviewCard) */}
      {previewOpen && previewReviewId && typeof document !== "undefined"
        ? createPortal(
            <div
              className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-sm"
              role="dialog"
              aria-modal="true"
              aria-label="Document preview"
              onMouseDown={(e) => {
                if (e.target === e.currentTarget) {
                  setPreviewOpen(false)
                  setPreviewReviewId(null)
                }
              }}
            >
              <div className="w-[min(980px,calc(100vw-32px))] max-h-[calc(100vh-24px)] flex flex-col">
                <div className="mb-2 flex justify-end">
                  <button
                    type="button"
                    onClick={() => {
                      setPreviewOpen(false)
                      setPreviewReviewId(null)
                    }}
                    className="grid h-10 w-10 place-items-center rounded-md border border-border bg-card text-muted-foreground shadow-sm hover:bg-accent hover:text-foreground"
                    aria-label="Close"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
                {(() => {
                  const versions = versionsByReview[previewReviewId] || []
                  const selectedVerId = selectedVersionByReview[previewReviewId]
                  const versionsLoading = !!versionsLoadingByReview[previewReviewId]

                  return (
                    <div className="mb-2 rounded-xl border bg-white px-3 py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        {versionsLoading ? (
                          <span className="text-xs text-muted-foreground">Loading versions...</span>
                        ) : versions.length > 0 ? (
                          versions.map((v, idx) => {
                            const selected = selectedVerId ? selectedVerId === v.id : idx === 0
                            return (
                              <button
                                key={v.id}
                                type="button"
                                onClick={() =>
                                  setSelectedVersionByReview((prev) => ({ ...prev, [previewReviewId]: v.id }))
                                }
                                className={cn(
                                  "rounded-lg px-3 py-1.5 text-xs font-semibold",
                                  selected
                                    ? "border border-foreground/10 bg-[#128BDA] text-white"
                                    : "border border-foreground/15 bg-transparent text-muted-foreground hover:text-foreground"
                                )}
                              >
                                {v.label}
                                {idx === 0 ? <span className="ml-1 font-medium">(Latest)</span> : null}
                              </button>
                            )
                          })
                        ) : (
                          <span className="text-xs text-muted-foreground">No versions available.</span>
                        )}
                      </div>
                    </div>
                  )
                })()}
                {(() => {
                  const row = rows.find((r) => r.reviewId === previewReviewId)
                  const versions = versionsByReview[previewReviewId] || []
                  const selectedVerId = selectedVersionByReview[previewReviewId]
                  const version = versions.find((v) => v.id === selectedVerId) || versions[0]
                  // const text = version?.text || "Loading content..."
                  // const paragraphs = text.split("\n").filter((p) => p.trim())
                  // const displayName = row?.document || previewFile?.fileName || "Original Document"

                  if (previewFileLoading) {
                    return (
                      <div className="rounded-xl border border-border bg-card px-6 py-16 text-center text-sm text-muted-foreground">
                        Loading original document from storage…
                      </div>
                    )
                  }
                  if (previewFileError) {
                    return (
                      <div className="rounded-xl border border-border bg-card px-6 py-16 text-center text-sm text-destructive">
                        {previewFileError}
                      </div>
                    )
                  }

                  return (
                    <DocumentPreviewCard
                      reviewerName={row?.performedBy || "Auditor"}
                      // reviewerSubLabel={row?.action || "Review Activity"}
                      status={
                        row?.status === "published" || row?.status === "approved"
                          ? "approved"
                          : row?.status === "rejected"
                            ? "rejected"
                            : "in-review"
                      }
                      // documentTitle={displayName}
                      // paragraphs={paragraphs}
                      fileUrl={previewFile?.url}
                      fileName={previewFile?.fileName}
                      mime={previewFile?.mime}
                      viewOnly
                      hideRules
                    />
                  )
                })()}
              </div>
            </div>,
            document.body
          )
        : null}
    </MainLayout>
  )
}
