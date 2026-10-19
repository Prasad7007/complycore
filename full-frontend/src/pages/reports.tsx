import * as React from "react"
import { Navigate, useParams, Link } from "react-router-dom"
import { FileIcon } from "@/components/icons/FileIcon"

import { MainLayout } from "@/components/layout/MainLayout"
import { CommonHeaderCard } from "@/components/layout/common-header-card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"
import { FilterableTableCard, type TableColumn } from "@/components/dashboard/RecentItemsTable"
import { reportsApi, type ComplianceReportRow } from "@/lib/api"
import { downloadReportPdf, downloadComplianceReportTxt } from "@/lib/report-export"
import { loadComplianceReportExportPayload } from "@/lib/compliance-report-export-data"

function formatShortDate(isoStr: string) {
  if (!isoStr) return ""
  const d = new Date(isoStr)
  if (isNaN(d.getTime())) return isoStr
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`
}

function Avatar({ name }: { name: string }) {
  const initials = name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("")

  return (
    <div className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-foreground/10 text-[10px] font-semibold text-foreground">
      {initials || "U"}
    </div>
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
  options: string[]
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
          <option key={o} value={o} className="bg-background">
            {o}
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

function getPageRange(current: number, total: number, windowSize = 5) {
  const half = Math.floor(windowSize / 2)
  let start = Math.max(1, current - half)
  let end = Math.min(total, start + windowSize - 1)
  start = Math.max(1, end - windowSize + 1)
  return Array.from({ length: end - start + 1 }, (_, i) => start + i)
}

export default function ReportsPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>()
  const [rows, setRows] = React.useState<ComplianceReportRow[]>([])
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    if (!orgSlug?.trim()) {
      setLoading(false)
      return
    }
    reportsApi.list(orgSlug).then(setRows).finally(() => setLoading(false))
  }, [orgSlug])

  const [headerSearch, setHeaderSearch] = React.useState("")
  const [reportId, setReportId] = React.useState("")
  const [docName, setDocName] = React.useState("")
  const [reviewType, setReviewType] = React.useState("")
  const [dateFrom, setDateFrom] = React.useState("")
  const [dateTo, setDateTo] = React.useState("")

  const [applied, setApplied] = React.useState({
    reportId: "",
    docName: "",
    reviewType: "",
    dateFrom: "",
    dateTo: "",
  })

  const filtered = React.useMemo(() => {
    const headerQ = headerSearch.trim().toLowerCase()
    const idQ = applied.reportId.trim().toLowerCase()
    const nameQ = applied.docName.trim().toLowerCase()
    const typeQ = applied.reviewType
    const fromQ = applied.dateFrom
    const toQ = applied.dateTo

    return rows.filter((r) => {
      const reportCode = r.report_code.toLowerCase()
      const normalizedDocName = (r.document_name || "Unknown").toLowerCase()
      if (headerQ && !reportCode.includes(headerQ) && !normalizedDocName.includes(headerQ)) return false
      if (idQ && !r.report_code.toLowerCase().includes(idQ)) return false
      const docName = r.document_name || "Unknown"
      if (nameQ && !docName.toLowerCase().includes(nameQ)) return false
      if (typeQ && r.review_type !== typeQ) return false

      const dateOnly = r.created_at ? r.created_at.split("T")[0] : ""
      if (fromQ && dateOnly < fromQ) return false
      if (toQ && dateOnly > toQ) return false
      return true
    })
  }, [applied.docName, applied.reportId, applied.reviewType, applied.dateFrom, applied.dateTo, headerSearch, rows])

  const pageSize = 10
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const [page, setPage] = React.useState(1)

  React.useEffect(() => {
    setPage(1)
  }, [filtered.length])

  const pageRows = React.useMemo(() => {
    const start = (page - 1) * pageSize
    return filtered.slice(start, start + pageSize)
  }, [filtered, page])

  const reviewTypeOptions = React.useMemo(
    () => Array.from(new Set(rows.map((r) => r.review_type))).filter(Boolean).sort(),
    [rows]
  )

  const [exportingId, setExportingId] = React.useState<string | null>(null)

  const handleExportTXT = React.useCallback(async (report: ComplianceReportRow) => {
    if (!orgSlug?.trim()) return
    setExportingId(report.id)
    try {
      const { findings, auditEvents } = await loadComplianceReportExportPayload(orgSlug, report.review_id)
      downloadComplianceReportTxt(report, findings, auditEvents)
    } catch (err) {
      console.error("Export TXT failed", err)
      try {
        const fallback = `Compliance Report ${report.report_code}\nDocument: ${report.document_name || "Unknown"}\nStatus: ${report.compliance_status || "pending"}`
        const blob = new Blob([fallback], { type: "text/plain" })
        const url = URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.style.display = "none"
        a.href = url
        a.download = `compliance-report-${report.report_code}.txt`
        document.body.appendChild(a)
        a.click()
        window.URL.revokeObjectURL(url)
        document.body.removeChild(a)
      } catch (inner) {
        console.error("TXT fallback failed", inner)
      }
    } finally {
      setExportingId(null)
    }
  }, [orgSlug])

  const handleExportPDF = React.useCallback(async (report: ComplianceReportRow) => {
    if (!orgSlug?.trim()) return
    setExportingId(report.id)
    try {
      const { findings, auditEvents } = await loadComplianceReportExportPayload(orgSlug, report.review_id)
      downloadReportPdf(report, findings, auditEvents)
    } catch (err) {
      console.error("Export PDF failed", err)
      try {
        downloadReportPdf(report, [], [])
      } catch (inner) {
        console.error("PDF fallback failed", inner)
      }
    } finally {
      setExportingId(null)
    }
  }, [orgSlug])

  const columns = React.useMemo<TableColumn<ComplianceReportRow>[]>(
    () => [
      {
        key: "reportId",
        header: "Report ID",
        headerClassName: "w-[90px]",
        cellClassName: "text-muted-foreground",
        render: (r) => (
          <Link
            to={`/orgs/${encodeURIComponent(orgSlug || "")}/reports/${r.id}`}
            className="text-primary font-medium hover:underline"
          >
            {r.report_code}
          </Link>
        ),
      },
      {
        key: "document",
        header: "Document/Pack Name",
        render: (r) => (
          <div className="flex min-w-0 items-start gap-2">
            <FileIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <div className="font-medium text-foreground whitespace-normal break-words md:truncate">
              {r.document_name || "Unknown Document"}
            </div>
          </div>
        ),
      },
      {
        key: "reviewType",
        header: "Review Type",
        headerClassName: "w-[130px]",
        hideBelow: "md",
        cellClassName: "text-muted-foreground",
        render: (r) => r.review_type === "social_post" ? "Social Media" : "Document",
      },
      {
        key: "totalFlags",
        header: "Total Flags",
        headerClassName: "w-[100px] text-center",
        hideBelow: "md",
        cellClassName: "text-center text-muted-foreground",
        render: (r) => r.total_flags ?? 0,
      },
      {
        key: "authority",
        header: "Approval Authority",
        headerClassName: "w-[190px]",
        hideBelow: "md",
        render: (r) => (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Avatar name={r.approval_authority_name || "User"} />
            <span className="whitespace-pre-wrap">{`${r.approval_authority_name || "Unknown"}\n${r.approval_role || "Reviewer"}`}</span>
          </div>
        ),
      },
      {
        key: "approvalDateTime",
        header: "Approval Date Time",
        headerClassName: "w-[150px]",
        hideBelow: "lg",
        cellClassName: "text-muted-foreground",
        render: (r) => <span className="whitespace-normal break-words">{formatShortDate(r.approval_timestamp)}</span>,
      },
    {
        key: "export",
        header: <span className="block text-center">Export</span>,
        headerClassName: "w-[160px] text-center",
        cellClassName: "text-center",
        render: (r) => (
          <div className="flex items-center justify-center gap-3">
            <button 
              type="button" 
              className="flex items-center gap-2 hover:opacity-80 transition-opacity disabled:opacity-50"
              onClick={() => handleExportPDF(r)}
              disabled={exportingId === r.id}
            >
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#E3F5FF] dark:bg-sky-950/50 dark:ring-1 dark:ring-sky-800/60">
                <img src="/shared/FileIconWithPDFText.svg" alt="PDF" className="h-4 w-4 dark:invert" />
              </div>
              <span className="text-sm text-muted-foreground">{exportingId === r.id ? "..." : "PDF"}</span>
            </button>
            <button 
              type="button" 
              className="flex items-center gap-2 hover:opacity-80 transition-opacity disabled:opacity-50"
              onClick={() => handleExportTXT(r)}
              disabled={exportingId === r.id}
            >
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#F4F2FF] dark:bg-violet-950/50 dark:ring-1 dark:ring-violet-800/60">
                <span className="text-[11px] font-semibold text-[#4B3FA8] dark:text-violet-300">TXT</span>
              </div>
              <span className="text-sm text-muted-foreground">{exportingId === r.id ? "..." : "TXT"}</span>
            </button>
          </div>
        ),
      },
    ],
    [exportingId, handleExportPDF, handleExportTXT]
  )

  if (!orgSlug?.trim()) {
    return <Navigate to="/pending-access" replace />
  }

  return (
    <MainLayout
      header={{
        breadcrumbs: [
          { label: "ComplyCore", to: `/orgs/${encodeURIComponent(orgSlug)}/dashboard/default` },
          { label: "Reports" },
        ],
        searchQuery: headerSearch,
        onSearchChange: setHeaderSearch,
        searchPlaceholder: "Search documents",
      }}
    >
      <div className="space-y-6">
        <div>
          <div className="text-sm font-semibold text-foreground">Compliance Reports</div>
          <div className="mt-1 text-xs text-muted-foreground">
            Generated compliance review summaries and reports
          </div>
        </div>

        {/* Filters (re-using CommonHeaderCard as a container) */}
        <CommonHeaderCard>
          <div className="p-5">
            <div className="grid gap-3 md:grid-cols-[1fr_1.2fr_1fr_1fr_1fr_auto] md:items-end">
              <div className="space-y-2">
                <Label className="text-xs font-semibold" htmlFor="reportId">
                  Report ID
                </Label>
                <Input
                  id="reportId"
                  placeholder="Text"
                  value={reportId}
                  onChange={(e) => setReportId(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label className="text-xs font-semibold" htmlFor="docName">
                  Document Name
                </Label>
                <Input
                  id="docName"
                  placeholder="Text"
                  value={docName}
                  onChange={(e) => setDocName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label className="text-xs font-semibold" htmlFor="reviewType">
                  Review Type
                </Label>
                <SelectField
                  id="reviewType"
                  value={reviewType}
                  onChange={setReviewType}
                  options={reviewTypeOptions}
                  placeholder="Select"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-xs font-semibold" htmlFor="dateFrom">
                  Date From
                </Label>
                <Input
                  id="dateFrom"
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="h-10 bg-background"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-xs font-semibold" htmlFor="dateTo">
                  Date To
                </Label>
                <Input
                  id="dateTo"
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="h-10 bg-background"
                />
              </div>
              <div className="flex">
                <Button
                  className="h-10 w-full rounded-md bg-[#128BDA] px-8 font-semibold text-white hover:bg-[#128BDA]/90 md:w-auto"
                  type="button"
                  onClick={() => setApplied({ reportId, docName, reviewType, dateFrom, dateTo })}
                >
                  Apply
                </Button>
              </div>
            </div>
          </div>
        </CommonHeaderCard>

        {loading ? (
          <div className="flex justify-center p-8 text-sm text-muted-foreground">Loading...</div>
        ) : (
          <FilterableTableCard
            className="shadow-sm"
            tableLayout="auto"
            columns={columns}
            rows={pageRows}
            rowKey={(r, i) => `${r.id}-${i}`}
            noRowHover
          footer={
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                aria-label="Previous page"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6"/></svg>
              </button>

              {getPageRange(page, totalPages, 5).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPage(p)}
                  className={cn(
                    "grid h-8 w-8 place-items-center rounded-md text-sm",
                    p === page
                      ? "bg-foreground/5 text-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  )}
                  aria-current={p === page ? "page" : undefined}
                >
                  {p}
                </button>
              ))}

              <button
                type="button"
                className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                aria-label="Next page"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m9 18 6-6-6-6"/></svg>
              </button>
            </div>
          }
        />
        )}
      </div>
    </MainLayout>
  )
}
