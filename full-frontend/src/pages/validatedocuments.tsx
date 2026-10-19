import * as React from "react"
import { Navigate, useNavigate, useParams } from "react-router-dom"
 
import { MainLayout } from "@/components/layout/MainLayout"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
 
import { CommonHeaderCard } from "@/components/layout/common-header-card"
import { FilterableTableCard } from "@/components/dashboard/RecentItemsTable"
import type { TableColumn } from "@/components/dashboard/RecentItemsTable"
import { cn } from "@/lib/utils"
import {
  ChevronLeft,
  ChevronRight
} from "lucide-react"
import { FileIcon } from "@/components/icons/FileIcon"
import { documentsApi } from "@/lib/api"
 
type WorkflowStage =
  | "Compliance Review"
  | "Published"
  | "Rejected"
  | "SME Review"
  | "Marketing Review"
  | "Approved"
  | "Needs revision"

/** Display-only: classifier / skip status maps to these two labels */
type DocumentType = "Educational" | "Non-educational"

const DOCUMENT_TYPE_FILTER_OPTIONS: DocumentType[] = ["Educational", "Non-educational"]

/** Workflow stages available in the Validate Documents filter. */
const WORKFLOW_STAGE_FILTER_OPTIONS: string[] = [
  "SME Review",
  "Marketing Review",
  "Compliance Review",
  "Needs revision",
  "Approved",
  "Published",
  "Rejected",
]
 
type DocumentRow = {
  id: string
  docId?: string
  review_id?: string
  status?: string
  name: string
  type: DocumentType
  version: string
  reviewer: string
  workflowStage: WorkflowStage
  lastUpdated: string
}
 
function Avatar({
  name,
  size = 22,
}: {
  name: string
  size?: number
}) {
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
 
function Pill({
  children,
  variant,
}: {
  children: React.ReactNode
  variant: "amber" | "red" | "green" | "blue" | "gray"
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-2.5 py-1 text-xs font-medium border",
        variant === "amber" && "border-[#FF8D28] bg-[#FF8D28]/5 text-[#FF8D28]",
        variant === "red" && "border-[#FF383C] bg-[#FF383C]/5 text-[#FF383C]",
        variant === "green" && "border-[#00C8B3] bg-[#00C8B3]/5 text-[#00C8B3]",
        variant === "blue" && "border-sky-200 bg-sky-50 text-sky-800",
        variant === "gray" && "border-foreground/10 bg-foreground/5 text-muted-foreground"
      )}
    >
      {children}
    </span>
  )
}
 
function stagePill(stage: WorkflowStage | string, status?: string) {
  if ((status || "").toLowerCase() === "failed") {
    return <Pill variant="red">Failed</Pill>
  }
  if (
    stage === "Compliance Review" ||
    stage === "SME Review" ||
    stage === "Marketing Review" ||
    stage === "Needs revision"
  ) {
    return <Pill variant="amber">{stage}</Pill>
  }
  if (stage === "Rejected") return <Pill variant="red">{stage}</Pill>
  if (stage === "Published") return <Pill variant="green">{stage}</Pill>
  if (stage === "Approved") return <Pill variant="green">{stage}</Pill>
  return <Pill variant="gray">{stage}</Pill>
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
 
function mapWorkflowStage(stage: string | null | undefined): WorkflowStage {
  const stageMap: Record<string, WorkflowStage> = {
    sme_review: "SME Review",
    marketing_review: "Marketing Review",
    compliance_review: "Compliance Review",
    approved: "Approved",
    published: "Published",
    rejected: "Rejected",
    needs_revision: "Needs revision",
  }
  return stageMap[stage.toLowerCase()]
}
 
function mapDocumentType(_type: string | null | undefined, status?: string | null): DocumentType {
  if ((status || "").toLowerCase() === "skipped") return "Non-educational"
  return "Educational"
}
 
function getPageRange(current: number, total: number, windowSize = 5) {
  const half = Math.floor(windowSize / 2)
  let start = Math.max(1, current - half)
  const end = Math.min(total, start + windowSize - 1)
  start = Math.max(1, end - windowSize + 1)
  return Array.from({ length: end - start + 1 }, (_, i) => start + i)
}
 
export default function ValidateDocumentsPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>()
  const navigate = useNavigate()
  const [rows, setRows] = React.useState<DocumentRow[]>([])
  const [loading, setLoading] = React.useState(true)

  // Fetch documents from backend
  React.useEffect(() => {
    const fetchDocuments = async () => {
      if (!orgSlug?.trim()) {
        setLoading(false)
        return
      }
      try {
        setLoading(true)
        const docs = await documentsApi.list(orgSlug)
        // Filter out only published docs. Keep classifier-skipped docs visible in this tab.
        const nonPublishedDocs = docs.filter((doc) => {
          const type = mapDocumentType(doc.type, doc.status)
        
          return (
            doc.workflow_stage !== "published" &&
            type === "Educational"   // 👈 MAIN FILTER
          )
        })
        const mappedRows: DocumentRow[] = nonPublishedDocs.map((doc: {
          id?: string
          document_code?: string
          name?: string
          type?: string
          status?: string
          version_label?: string
          workflow_stage?: string
          assigned_to?: string
          assigned_to_name?: string
          updated_at?: string
          created_at?: string
          review_id?: string
        }, index: number) => {
          let displayId = ""
          if (doc.document_code && doc.document_code.startsWith("DOC-")) {
            displayId = doc.document_code.replace("DOC-", "")
          } else if (doc.document_code) {
            displayId = doc.document_code
          } else {
            // Fallback for older documents without a document_code
            displayId = String(index + 1).padStart(3, '0')
          }
 
          const mappedStage = mapWorkflowStage(doc.workflow_stage)
          const assignedName = (doc.assigned_to_name || doc.assigned_to || "").trim()
          const shouldShowUnassigned =
            (mappedStage === "SME Review" || mappedStage === "Compliance Review") &&
            assignedName.length === 0

          return {
          id: displayId,
          docId: doc.id,
          name: doc.name || "Untitled Document",
          status: doc.status,
          type: mapDocumentType(doc.type, doc.status),
          version: doc.version_label || "v1",
          reviewer: shouldShowUnassigned ? "Unassigned" : assignedName || "Unassigned",
          workflowStage: mappedStage,
          lastUpdated: (() => {
            const raw = doc.updated_at || doc.created_at || new Date().toISOString()
            const utc = raw.endsWith("Z") ? raw : raw + "Z"
            const date = new Date(utc)
            return `${(date.getMonth() + 1).toString().padStart(2, '0')}-${date.getDate().toString().padStart(2, '0')} ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
          })(),
          review_id: doc.review_id,
        }
        })
        setRows(mappedRows)
      } catch (error: any) {
        console.error("Failed to fetch documents:", error)
      } finally {
        setLoading(false)
      }
    }
    fetchDocuments()
  }, [orgSlug])

 
  // list filters
  const [headerSearch, setHeaderSearch] = React.useState("")
  const [docId, setDocId] = React.useState("")
  const [docName, setDocName] = React.useState("")
  const [docType, setDocType] = React.useState("")
  const [workflowStage, setWorkflowStage] = React.useState("")
 
  // applied filters (Apply button)
  const [applied, setApplied] = React.useState({
    docId: "",
    docName: "",
    docType: "",
    workflowStage: "",
  })
 
  const filtered = React.useMemo(() => {
    const headerQ = headerSearch.trim().toLowerCase()
    const idQ = applied.docId.trim().toLowerCase()
    const nameQ = applied.docName.trim().toLowerCase()
    const typeQ = applied.docType
    const stageQ = applied.workflowStage

    return rows.filter((r) => {
      if (headerQ && !r.id.toLowerCase().includes(headerQ) && !r.name.toLowerCase().includes(headerQ)) return false
      if (idQ && !r.id.toLowerCase().includes(idQ)) return false
      if (nameQ && !r.name.toLowerCase().includes(nameQ)) return false
      if (typeQ && r.type !== typeQ) return false
      if (stageQ && r.workflowStage !== stageQ) return false
      return true
    })
  }, [applied.docId, applied.docName, applied.docType, applied.workflowStage, headerSearch, rows])
 
  const pageSize = 9
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const [page, setPage] = React.useState(1)
 
  React.useEffect(() => {
    setPage(1)
  }, [filtered.length])
 
  const pageRows = React.useMemo(() => {
    const start = (page - 1) * pageSize
    return filtered.slice(start, start + pageSize)
  }, [filtered, page])
 
  const docColumns: TableColumn<DocumentRow>[] = React.useMemo(() => [
            {
              key: "id",
              header: "ID",
              headerClassName: "w-[100px]",
              cellClassName: "align-middle",
              render: (r) => <span className="text-muted-foreground">{r.id}</span>
            },
            {
              key: "document",
              header: "Document",
              render: (r) => (
                <div className="flex items-start gap-2">
                  <FileIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="font-medium text-foreground">{r.name}</div>
                </div>
              ),
            },
            {
              key: "type",
              header: "Type",
              headerClassName: "w-[140px]",
              cellClassName: "text-muted-foreground",
              hideBelow: "md",
              render: (r) => r.type,
            },
            {
              key: "version",
              header: "Version",
              headerClassName: "w-[80px]",
              cellClassName: "text-muted-foreground",
              hideBelow: "md",
              render: (r) => r.version,
            },
            {
              key: "reviewer",
              header: "Reviewer",
              headerClassName: "w-[160px]",
              cellClassName: "whitespace-pre-wrap text-muted-foreground",
              hideBelow: "md",
              render: (r) => r.reviewer,
            },
            {
              key: "stage",
              header: "Workflow Stage",
              headerClassName: "w-[150px]",
              render: (r) => stagePill(r.workflowStage, r.status),
            },
            {
              key: "updated",
              header: "Last Updated",
              headerClassName: "w-[130px]",
              cellClassName: "text-muted-foreground",
              hideBelow: "lg",
              render: (r) => r.lastUpdated,
            },
            {
              key: "action",
              header: <span className="block text-center">Action</span>,
              headerClassName: "w-[120px] sm:w-[220px] text-center",
              cellClassName: "text-center",
              render: (r) => (
                (() => {
                  const isSkipped = (r.status || "").toLowerCase() === "skipped"
                  const isFailed = (r.status || "").toLowerCase() === "failed"
                  const isDisabled = isSkipped || isFailed
                  return (
                <div className="flex items-center justify-center gap-2 md:gap-3">
                  <Button
                    variant="outline"
                    size="icon"
                    className="h-9 w-9 border-0 bg-muted hover:bg-accent md:hidden"
                    aria-label="Review"
                    onClick={() => !isDisabled && navigate(`/orgs/${encodeURIComponent(orgSlug)}/validate-documents/detail/${r.docId}`)}
                    disabled={isDisabled}
                  >
                    <img
                      src="/documents/fileIcon.svg"
                      alt=""
                      className="h-4 w-4 shrink-0 dark:invert"
                    />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="hidden h-9 gap-2 border-0 bg-muted hover:bg-accent md:inline-flex"
                    onClick={() => !isDisabled && navigate(`/orgs/${encodeURIComponent(orgSlug)}/validate-documents/detail/${r.docId}`)}
                    disabled={isDisabled}
                  >
                    <img src="/documents/fileIcon.svg" alt="" className="h-4 w-4 shrink-0 dark:invert" />
                    Review
                  </Button>
                </div>
                  )
                })()
              ),
            },
  ], [navigate, orgSlug])

  if (!orgSlug?.trim()) {
    return <Navigate to="/pending-access" replace />
  }

  return (
    <MainLayout
      header={{
        breadcrumbs: [
          { label: "ComplyCore", to: `/orgs/${encodeURIComponent(orgSlug)}/dashboard/default` },
          { label: "Documents" },
        ],
        searchQuery: headerSearch,
        onSearchChange: setHeaderSearch,
        searchPlaceholder: "Search documents",
      }}
    >
      <div className="space-y-6">
        <div>
          <div className="text-sm font-semibold text-foreground">Document Review</div>
          <div className="mt-1 text-xs text-muted-foreground">
            Review and manage marketing documents for NI 31-103 compliance
          </div>
        </div>
 
        {loading && (
          <div className="flex items-center justify-center p-8">
            <div className="text-sm text-muted-foreground">Loading documents...</div>
          </div>
        )}
 
        {!loading && (
          <>
            {/* Filters */}
            <CommonHeaderCard>
              <div className="p-5">
                <div className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_1fr_auto] md:items-end">
                  <div className="space-y-2">
                    <Label className="text-xs font-semibold" htmlFor="docId">
                      Document ID
                    </Label>
                    <Input
                      id="docId"
                      placeholder="Text"
                      value={docId}
                      onChange={(e) => setDocId(e.target.value)}
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
                    <Label className="text-xs font-semibold" htmlFor="docType">
                      Type
                    </Label>
                    <SelectField
                      id="docType"
                      value={docType}
                      onChange={setDocType}
                      options={DOCUMENT_TYPE_FILTER_OPTIONS}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs font-semibold" htmlFor="workflowStage">
                      Workflow Stage
                    </Label>
                    <SelectField
                      id="workflowStage"
                      value={workflowStage}
                      onChange={setWorkflowStage}
                      options={WORKFLOW_STAGE_FILTER_OPTIONS}
                    />
                  </div>
                  <div className="flex">
                    <Button
                      className="h-10 rounded-md bg-[#5BC0EB] px-8 font-semibold text-white shadow-sm hover:bg-[#5BC0EB]/90"
                      type="button"
                      onClick={() =>
                        setApplied({
                          docId,
                          docName,
                          docType,
                          workflowStage,
                        })
                      }
                    >
                      Apply
                    </Button>
                  </div>
                </div>
              </div>
            </CommonHeaderCard>
 
            {/* Table */}
            <FilterableTableCard
              className=""
              noRowHover
              tableLayout="auto"
              columns={docColumns}
              rows={pageRows}
              rowKey={(r, i) => `${(page - 1) * pageSize + i}-${r.id}`}
              footer={
                <div className="flex items-center justify-end gap-2 px-1 py-1">
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
          </>
        )}
      </div>
    </MainLayout>
  )
}
