import * as React from "react"
import { ChevronLeft, ChevronRight, Eye } from "lucide-react"
import { FileIcon } from "@/components/icons/FileIcon"
import { Navigate, useNavigate, useParams } from "react-router-dom"

import { MainLayout } from "@/components/layout/MainLayout"
import { CommonHeaderCard } from "@/components/layout/common-header-card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"
import { FilterableTableCard, type TableColumn } from "@/components/dashboard/RecentItemsTable"
import { documentsApi, auditApi } from "@/lib/api"

type PublishedRow = {
  id: string
  docId: string
  documentName: string
  category: string
  publishedAt: string
  /** UTC ms for range filter (publishedAt is locale-formatted and not parseable for comparisons). */
  publishedAtMs: number
  publishedBy: string
  approvedAt: string
  approvedBy: string
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
        className="h-10 w-full appearance-none rounded-md border border-input bg-background px-3 pr-9 text-sm text-foreground shadow-sm outline-none focus:ring-1 focus:ring-ring"
      >
        <option value="">{placeholder}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
      <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 flex flex-col items-center gap-[2px]">
        <svg width="8" height="5" viewBox="0 0 8 5" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M1 4L4 1L7 4" stroke="#6B7280" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <svg width="8" height="5" viewBox="0 0 8 5" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M1 1L4 4L7 1" stroke="#6B7280" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </span>
    </div>
  )
}

function mapDocumentType(type: string | null | undefined, status?: string | null): string {
  if ((status || "").toLowerCase() === "skipped") return "Non-educational"
  if (!type) return "Educational"
  const typeMap: Record<string, string> = {
    educational_content: "Educational",
    educational_document: "Educational",
    performance_related: "Performance-related",
    client_communications: "Client Communications",
    opinion: "Opinion",
    product_feature: "Performance-related",
    disclosure: "Educational",
  }
  return typeMap[type.toLowerCase()] || "Educational"
}

function formatDateTimeSafe(
  value: string | number | Date | null | undefined
): string | null {
  if (value == null || value === "") return null
  const valStr = typeof value === "string" ? (value.endsWith("Z") ? value : value + "Z") : value
  const date = new Date(valStr)
  if (Number.isNaN(date.getTime())) return null
  return `${(date.getMonth() + 1).toString().padStart(2, '0')}-${date.getDate().toString().padStart(2, '0')} ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
}

function getPageRange(current: number, total: number, windowSize = 5) {
  const half = Math.floor(windowSize / 2)
  let start = Math.max(1, current - half)
  let end = Math.min(total, start + windowSize - 1)
  start = Math.max(1, end - windowSize + 1)
  return Array.from({ length: end - start + 1 }, (_, i) => start + i)
}

export default function PublishedDocumentsPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>()
  const navigate = useNavigate()
  const [rows, setRows] = React.useState<PublishedRow[]>([])
  const [loading, setLoading] = React.useState(true)

  // Fetch published documents from backend
  React.useEffect(() => {
    const fetchPublishedDocuments = async () => {
      if (!orgSlug?.trim()) {
        setLoading(false)
        return
      }
      try {
        setLoading(true)
        const docs = await documentsApi.list(orgSlug)
        // Filter only published documents (exclude classifier-skipped)
        const publishedDocs = docs.filter((doc) => {
          const category = mapDocumentType(doc.type, doc.status)
        
          return (
            doc.workflow_stage === "published" &&
            doc.status !== "skipped" &&
            category === "Educational"   // 👈 MAIN FILTER
          )
        })
        
        // Fetch workflow steps to get published_at and published_by info
        const mappedRows: PublishedRow[] = await Promise.all(
          publishedDocs.map(async (doc: {
            id?: string
            document_code?: string
            name?: string
            type?: string
            status?: string
            review_id?: string
            updated_at?: string
            created_at?: string
          }, index: number) => {
            let displayId = ""
            if (doc.document_code && doc.document_code.startsWith("DOC-")) {
              displayId = doc.document_code.replace("DOC-", "")
            } else if (doc.document_code) {
              displayId = doc.document_code
            } else {
              displayId = String(index + 1).padStart(3, "0")
            }

            // Fetch workflow steps to get publish action details
            let publishedAt = ""
            let publishedBy = "System"
            let approvedAt = ""
            let approvedBy = ""
            let rawPublished: string | number | Date =
              doc.updated_at || doc.created_at || Date.now()

            if (doc.review_id) {
              try {
                const response = await auditApi.getAuditTrail(orgSlug, doc.review_id)
                const steps = response.workflow_steps || (Array.isArray(response) ? response : [])
                const publishStep = steps.find((s: any) => s.action === "publish" && s.stage === "published")
                // Find the compliance approval step - when compliance approves and locks,
                // the step has action='approve_and_lock', stage='approved', and previous_stage='compliance_review'
                const approveStep = steps.find((s: any) => 
                  s.action === "approve_and_lock" && 
                  s.previous_stage === "compliance_review"
                )
                
                if (publishStep) {
                  rawPublished =
                    publishStep.completed_at || publishStep.created_at || rawPublished
                  publishedAt =
                    formatDateTimeSafe(rawPublished, {
                      year: "numeric",
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    }) || ""
                  publishedBy = publishStep.completed_by_name || publishStep.user_name || "System"
                }
                
                if (approveStep) {
                  approvedAt =
                    formatDateTimeSafe(approveStep.completed_at || approveStep.created_at, {
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    }) || ""
                  approvedBy = approveStep.completed_by_name || approveStep.user_name || "System"
                }
              } catch (err) {
                console.error("Failed to fetch workflow steps:", err)
              }
            }

            // Fallback to document updated_at if no publish step found
            if (!publishedAt) {
              rawPublished = doc.updated_at || doc.created_at || Date.now()
              publishedAt =
                formatDateTimeSafe(rawPublished, {
                  year: "numeric",
                  month: "2-digit",
                  day: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                }) || "N/A"
            }

            const publishedAtMs = (() => {
              const utc = rawPublished.endsWith("Z") ? rawPublished : rawPublished + "Z"
              const t = new Date(utc).getTime()
              return Number.isNaN(t) ? 0 : t
            })()

            return {
              id: displayId,
              docId: doc.id || "",
              documentName: doc.name || "Untitled Document",
              category: mapDocumentType(doc.type, doc.status),
              publishedAt,
              publishedAtMs,
              publishedBy,
              approvedAt: approvedAt || publishedAt,
              approvedBy: approvedBy || publishedBy || "System",
            }
          })
        )
        
        setRows(mappedRows)
      } catch (error: any) {
        console.error("Failed to fetch published documents:", error)
      } finally {
        setLoading(false)
      }
    }
    fetchPublishedDocuments()
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
      if (headerQ && !r.id.toLowerCase().includes(headerQ) && !r.documentName.toLowerCase().includes(headerQ)) return false
      if (idQ && !r.id.toLowerCase().includes(idQ)) return false
      if (nameQ && !r.documentName.toLowerCase().includes(nameQ)) return false
      if (typeQ && r.category !== typeQ) return false

      // publishedAt is locale-formatted; compare using publishedAtMs vs local calendar-day bounds
      if (fromQ) {
        const start = new Date(`${fromQ}T00:00:00.000`).getTime()
        if (!Number.isNaN(start) && r.publishedAtMs < start) return false
      }
      if (toQ) {
        const end = new Date(`${toQ}T23:59:59.999`).getTime()
        if (!Number.isNaN(end) && r.publishedAtMs > end) return false
      }
      return true
    })
  }, [applied.dateFrom, applied.dateTo, applied.docName, applied.reportId, applied.reviewType, headerSearch, rows])

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

  const columns = React.useMemo<TableColumn<PublishedRow>[]>(
    () => [
      {
        key: "id",
        header: "ID",
        headerClassName: "w-[70px]",
        cellClassName: "text-muted-foreground",
        render: (r) => r.id,
      },
      {
        key: "documentName",
        header: "Document name",
        render: (r) => (
          <div className="flex min-w-0 items-start gap-2">
            <FileIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <div className="whitespace-normal break-words font-medium text-foreground">{r.documentName}</div>
          </div>
        ),
      },
      {
        key: "category",
        header: "Category",
        headerClassName: "w-[180px]",
        hideBelow: "md",
        cellClassName: "text-muted-foreground",
        render: (r) => r.category,
      },
      {
        key: "publishedAt",
        header: "Published at",
        headerClassName: "w-[170px]",
        hideBelow: "lg",
        cellClassName: "text-muted-foreground",
        render: (r) => <span className="whitespace-normal break-words">{r.publishedAt}</span>,
      },
      {
        key: "publishedBy",
        header: "Published By",
        headerClassName: "w-[160px]",
        hideBelow: "md",
        render: (r) => (
          <div className="flex items-center gap-2">
            <Avatar name={r.publishedBy} />
            <span className="truncate text-foreground">{r.publishedBy}</span>
          </div>
        ),
      },
      {
        key: "approvedBy",
        header: "Approved By",
        headerClassName: "w-[150px]",
        hideBelow: "lg",
        render: (r) => (
          <div className="flex items-center gap-2">
            <Avatar name={r.approvedBy} />
            <span className="truncate text-foreground">{r.approvedBy}</span>
          </div>
        ),
      },
      {
        key: "action",
        header: <span className="block text-center">Action</span>,
        headerClassName: "w-[90px] text-center",
        cellClassName: "text-center",
        render: (r) => (
          <Button 
            variant="ghost" 
            size="icon" 
            className="h-9 w-9 bg-muted hover:bg-accent"
            aria-label="View"
            onClick={() =>
              navigate(`/orgs/${encodeURIComponent(orgSlug)}/validate-documents/detail/${r.docId}`)
            }
          >
            <Eye className="h-4 w-4" />
          </Button>
        ),
      },
    ],
    [navigate, orgSlug]
  )

  if (!orgSlug?.trim()) {
    return <Navigate to="/pending-access" replace />
  }

  return (
    <MainLayout
      header={{
        breadcrumbs: [
          { label: "ComplyCore", to: `/orgs/${encodeURIComponent(orgSlug)}/dashboard/default` },
          { label: "Published Documents" },
        ],
        searchQuery: headerSearch,
        onSearchChange: setHeaderSearch,
        searchPlaceholder: "Search documents",
      }}
    >
      <div className="space-y-6">
        <div>
          <div className="text-sm font-semibold text-foreground">Published Documents</div>
          <div className="mt-1 text-xs text-muted-foreground">
            View all published and approved documents
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
                  options={Array.from(new Set(rows.map((r) => r.category))).sort()}
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
          <div className="flex items-center justify-center py-12">
            <div className="text-sm text-muted-foreground">Loading published documents...</div>
          </div>
        ) : rows.length === 0 ? (
          <div className="flex items-center justify-center py-12">
            <div className="text-sm text-muted-foreground">No published documents found.</div>
          </div>
        ) : (
        <FilterableTableCard
          className="shadow-sm"
          tableLayout="auto"
          columns={columns}
          rows={pageRows}
          rowKey={(r, i) => `${r.id}-${i}`}
          footer={
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                aria-label="Previous page"
              >
                <ChevronLeft className="h-4 w-4" />
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
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          }
        />
        )}
      </div>
    </MainLayout>
  )
}

