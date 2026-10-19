import * as React from "react"
import { useNavigate } from "react-router-dom"
import { FileIcon } from "@/components/icons/FileIcon"
import { Clock } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn, formatDocumentType } from "@/lib/utils"
import { documentsApi } from "@/lib/api"

export type RecentItemRow = {
  id: string
  docId: string
  versionId: string
  reviewId: string
  document: string
  type: string
  version: string
  reviewer: string
  stage: { label: string; colorClassName: string; raw: string }
  updated: string
}

export type TableTabOption = { value: string; label: string }

export type TableColumn<T> = {
  key: string
  header: React.ReactNode
  /** Hide this column below the given breakpoint (e.g. hideBelow="md" => hidden on sm) */
  hideBelow?: "md" | "lg"
  headerClassName?: string
  cellClassName?: string
  render: (row: T, rowIndex: number) => React.ReactNode
}

export type FilterableTableCardProps<T> = {
  className?: string
  title?: React.ReactNode
  headerRight?: React.ReactNode
  tabs?: TableTabOption[]
  activeTab?: string
  onTabChange?: (value: string) => void
  /** Use "auto" to let columns shrink more evenly. */
  tableLayout?: "fixed" | "auto"
  columns: TableColumn<T>[]
  rows: T[]
  rowKey?: (row: T, index: number) => string
  emptyText?: string
  footer?: React.ReactNode
  /** Optional: returns true when this row should show its expanded content */
  isRowExpanded?: (row: T, rowIndex: number) => boolean
  /** Optional: renders a full-width row below the given row when expanded */
  renderExpandedRow?: (row: T, rowIndex: number) => React.ReactNode
  /** When true, disables the row hover background */
  noRowHover?: boolean
  /** Optional row click handler */
  onRowClick?: (row: T, rowIndex: number) => void
  /** Optional extra class for each row */
  getRowClassName?: (row: T, rowIndex: number) => string
}

function colVisibilityClass(hideBelow?: "md" | "lg") {
  if (!hideBelow) return ""
  return hideBelow === "md" ? "hidden md:table-cell" : "hidden lg:table-cell"
}

export function FilterableTableCard<T>({
  className,
  title,
  headerRight,
  tabs,
  activeTab,
  onTabChange,
  tableLayout = "fixed",
  columns,
  rows,
  rowKey,
  emptyText = "No results found.",
  footer,
  isRowExpanded,
  renderExpandedRow,
  noRowHover,
  onRowClick,
  getRowClassName,
}: FilterableTableCardProps<T>) {
  const showHeader = Boolean(title || headerRight)
  const showTabs = Boolean(tabs && tabs.length)

  return (
    <div className={cn("overflow-hidden rounded-xl bg-card", className)}>
      {showHeader ? (
        <div className="px-4 pt-5 md:px-6">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="text-sm font-semibold text-foreground">{title}</div>
            {headerRight ? <div>{headerRight}</div> : null}
          </div>
        </div>
      ) : null}

      {showTabs ? (
        <div className={cn("px-4 pt-3 md:px-6", !showHeader && "pt-5")}>
          <div className="flex items-center gap-2">
            {tabs!.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => onTabChange?.(t.value)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm transition-colors",
                  activeTab === t.value
                    ? "bg-muted font-semibold text-foreground"
                    : "font-medium text-muted-foreground hover:text-foreground"
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className={cn("overflow-x-auto", showTabs && "pt-0")}>
        <table
          className={cn(
            "w-full text-left text-sm",
            tableLayout === "fixed" ? "table-fixed" : "table-auto"
          )}
        >
          <thead className="bg-muted/30 text-[13px] text-foreground/60">
            <tr className="border-b border-foreground/10">
              {columns.map((c, idx) => (
                <th
                  key={c.key}
                  className={cn(
                    idx === 0 ? "" : "border-l border-foreground/10",
                    "px-3 py-3 md:px-4 font-normal",
                    colVisibilityClass(c.hideBelow),
                    c.headerClassName
                  )}
                >
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {rows.map((r, i) => (
              <React.Fragment key={rowKey ? rowKey(r, i) : String(i)}>
                <tr
                  className={cn(
                    "border-b border-foreground/10",
                    !noRowHover && "hover:bg-muted/50",
                    onRowClick && "cursor-pointer",
                    getRowClassName?.(r, i)
                  )}
                  onClick={(e) => {
                    if (!onRowClick) return
                    const target = e.target as HTMLElement | null
                    if (
                      target?.closest(
                        "button, a, input, select, textarea, [role='button'], [data-row-click-ignore='true']"
                      )
                    ) {
                      return
                    }
                    onRowClick(r, i)
                  }}
                >
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={cn(
                        "px-3 py-4 align-top overflow-hidden break-words md:px-4 md:align-middle",
                        colVisibilityClass(c.hideBelow),
                        c.cellClassName
                      )}
                    >
                      {c.render(r, i)}
                    </td>
                  ))}
                </tr>
                {isRowExpanded?.(r, i) && renderExpandedRow ? (
                  <tr className="border-b border-foreground/10 bg-card">
                    <td colSpan={columns.length} className="p-0">
                      {renderExpandedRow(r, i)}
                    </td>
                  </tr>
                ) : null}
              </React.Fragment>
            ))}

            {rows.length === 0 ? (
              <tr className="border-b border-foreground/10">
                <td
                  colSpan={Math.max(1, columns.length)}
                  className="px-6 py-10 text-center text-sm text-muted-foreground"
                >
                  {emptyText}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {footer ? <div className="px-4 py-3 md:px-6">{footer}</div> : null}
    </div>
  )
}

export function RecentItemsTable({
  orgSlug,
  initialRows = [],
  searchQuery = "",
}: {
  orgSlug: string
  initialRows?: RecentItemRow[]
  searchQuery?: string
}) {
  const navigate = useNavigate()
  const [rows, setRows] = React.useState<RecentItemRow[]>(initialRows)
  const [loading, setLoading] = React.useState(false)
  const [exportingReviewId, setExportingReviewId] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!orgSlug) return
    fetchDocuments()
  }, [orgSlug])

  const fetchDocuments = async () => {
    if (!orgSlug) return
    try {
      setLoading(true)
      const result = await documentsApi.list(orgSlug)
      if (Array.isArray(result)) {
        const mapped: RecentItemRow[] = result
  .filter((doc) => formatDocumentType(doc.type, doc.status) === "Educational") // 👈 MAIN FILTER
  .map((doc) => {
          let colorClassName = "border border-foreground/10 text-muted-foreground bg-muted"
          let label = doc.workflow_stage || "Pending"
          
          if ((doc.status || "").toLowerCase() === "failed") {
            label = "Failed"
            colorClassName = "border border-[#FF383C] bg-[#FF383C]/5 text-[#FF383C] dark:border-red-600 dark:bg-red-950/50 dark:text-red-400"
          } else if (label === "marketing_review" || label === "sme_review" || label === "compliance_review") {
            colorClassName = "border border-[#FF8D28] bg-[#FF8D28]/5 text-[#FF8D28] dark:border-amber-600 dark:bg-amber-950/50 dark:text-amber-400"
          } else if (label === "published" || label === "publish" || label === "approved") {
            colorClassName = "border border-[#00C8B3] bg-[#00C8B3]/5 text-[#00C8B3] dark:border-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400"
          } else if (label === "rejected") {
             colorClassName = "border border-[#FF383C] bg-[#FF383C]/5 text-[#FF383C] dark:border-red-600 dark:bg-red-950/50 dark:text-red-400"
          }

          // Format Date
          let dateStr = doc.updated_at
          if (doc.updated_at) {
            const raw = doc.updated_at
            const utc = raw.endsWith("Z") ? raw : raw + "Z"
            const date = new Date(utc)
            dateStr = `${(date.getMonth() + 1).toString().padStart(2, '0')}-${date.getDate().toString().padStart(2, '0')} ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
          }

          return {
            id: doc.document_code || doc.id?.substring(0, 6) || "-",
            docId: doc.id || "",
            versionId: doc.current_version_id || "",
            reviewId: doc.review_id || "",
            document: doc.name || "Unknown Document",
            type: formatDocumentType(doc.type, doc.status),
            version: doc.version_label || "1.0",
            reviewer: `${doc.assigned_to_name || doc.assigned_to || "Unassigned"}\n`,
            stage: {
              label: label.split('_').map((w: string) => w.charAt(0).toUpperCase() + w.slice(1)).join(' '),
              colorClassName,
              raw: doc.workflow_stage || "not_started",
            },
            updated: dateStr || "-",
          }
        })
        setRows(mapped)
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const filteredRows = React.useMemo(() => {
    if (!searchQuery.trim()) return rows
    const q = searchQuery.toLowerCase()
    return rows.filter((r) => {
      return (
        r.id.toLowerCase().includes(q) ||
        r.document.toLowerCase().includes(q) ||
        r.type.toLowerCase().includes(q)
      )
    })
  }, [rows, searchQuery])

  const handleDownloadDocument = React.useCallback(
    async (row: RecentItemRow) => {
      if (!row.versionId) {
        alert("No version found for this document.")
        return
      }

      setExportingReviewId(row.reviewId || row.docId)
      try {
        const res = await documentsApi.getVersionFileUrl(orgSlug, row.versionId, true)
        if (res && res.url) {
          const link = document.createElement("a")
          link.href = res.url
          link.target = "_blank"
          link.setAttribute("download", res.file_name || "document")
          document.body.appendChild(link)
          link.click()
          document.body.removeChild(link)
        } else {
          alert("Failed to get document download URL.")
        }
      } catch (e) {
        console.error("Failed to download document", e)
        alert("Failed to download document.")
      } finally {
        setExportingReviewId(null)
      }
    },
    [orgSlug]
  )


  const columns = React.useMemo<TableColumn<RecentItemRow>[]>(
    () => [
      {
        key: "id",
        header: "ID",
        headerClassName: "w-[56px] sm:w-[70px]",
        cellClassName: "text-muted-foreground",
        render: (r) => r.id,
      },
      {
        key: "document",
        header: "Document",
        headerClassName: "min-w-0",
        render: (r) => (
          <div className="flex min-w-0 items-start gap-2">
            <FileIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0">
              <div className="font-medium text-foreground whitespace-normal break-words">
                {r.document}
              </div>
              {/* sm summary details */}
              <div className="mt-1 space-y-0.5 text-xs text-muted-foreground md:hidden">
                <div className="truncate">{r.type}</div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="shrink-0">{r.version}</span>
                  <span className="text-muted-foreground/40">•</span>
                  <span className="whitespace-pre-wrap break-words">{r.reviewer}</span>
                </div>
                <div className="truncate">{r.updated}</div>
              </div>
            </div>
          </div>
        ),
      },
      {
        key: "type",
        header: "Type",
        hideBelow: "md",
        headerClassName: "w-[160px]",
        cellClassName: "text-muted-foreground",
        render: (r) => r.type,
      },
      {
        key: "version",
        header: "Version",
        hideBelow: "md",
        headerClassName: "w-[90px]",
        cellClassName: "text-muted-foreground",
        render: (r) => r.version,
      },
      {
        key: "reviewer",
        header: "Reviewer",
        hideBelow: "md",
        headerClassName: "w-[190px]",
        cellClassName: "whitespace-pre-wrap text-muted-foreground",
        render: (r) => r.reviewer,
      },
      {
        key: "stage",
        header: "Workflow Stage",
        headerClassName: "w-[140px] sm:w-[170px]",
        render: (r) => (
          <span
            className={cn(
              "inline-flex items-center rounded px-2.5 py-1 text-xs font-medium",
              r.stage.colorClassName
            )}
          >
            {r.stage.label}
          </span>
        ),
      },
      {
        key: "updated",
        header: "Last Updated",
        hideBelow: "lg",
        headerClassName: "w-[150px]",
        cellClassName: "text-muted-foreground",
        render: (r) => <span className="whitespace-nowrap">{r.updated}</span>,
      },
      {
        key: "action",
        header: <span className="block text-center">Action</span>,
        headerClassName: "min-w-[100px] md:min-w-[200px] text-center shrink-0",
        cellClassName: "text-right shrink-0",
        render: (r) => {
          const isFailedRow = (r.stage?.label || "").toLowerCase() === "failed"
          return (
          <div className="flex items-center justify-end gap-2">
            {/* sm: icon only */}
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 md:hidden shrink-0"
              aria-label="Download"
              onClick={() => !isFailedRow && handleDownloadDocument(r)}
              disabled={isFailedRow || exportingReviewId === (r.reviewId || r.docId)}
            >
              <img src="/shared/downloadIcon.svg" alt="" className="h-4 w-4 dark:invert" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 md:hidden shrink-0"
              aria-label="Audit Trail"
              onClick={() => !isFailedRow && navigate(`/orgs/${encodeURIComponent(orgSlug)}/audit-trail?reviewId=${encodeURIComponent(r.reviewId || "")}`)}
              disabled={isFailedRow}
            >
              <Clock className="h-4 w-4" />
            </Button>

            {/* md+: icon + label */}
            <Button
              variant="ghost"
              size="sm"
              className="hidden h-9 shrink-0 items-center gap-2 whitespace-nowrap px-2 text-muted-foreground hover:text-foreground md:inline-flex"
              type="button"
              onClick={() => !isFailedRow && handleDownloadDocument(r)}
              disabled={isFailedRow || exportingReviewId === (r.reviewId || r.docId)}
            >
              <img src="/shared/downloadIcon.svg" alt="" className="h-4 w-4 dark:invert" />
              Download
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="hidden h-9 shrink-0 items-center gap-2 whitespace-nowrap px-2 text-muted-foreground hover:text-foreground md:inline-flex"
              type="button"
              onClick={() => !isFailedRow && navigate(`/orgs/${encodeURIComponent(orgSlug)}/audit-trail?reviewId=${encodeURIComponent(r.reviewId || "")}`)}
              disabled={isFailedRow}
            >
              <Clock className="h-4 w-4" />
              Audit Trail
            </Button>
          </div>
          )
        },
      },
    ],
    [exportingReviewId, handleDownloadDocument, navigate, orgSlug]
  )

  return (
    <FilterableTableCard
      className="mt-6"
      title="Recent Items"
      tabs={[
        { value: "documents", label: "Documents" },
      ]}
      activeTab="documents"
      tableLayout="auto"
      emptyText={loading ? "Loading..." : "No results found."}
      columns={columns}
      rows={filteredRows}
      rowKey={(r, i) => `${r.id}-${i}`}
      onRowClick={(row) => {
        if ((row.stage?.label || "").toLowerCase() === "failed") return
        navigate(`/orgs/${encodeURIComponent(orgSlug)}/validate-documents/detail/${row.docId}`)
      }}
    />
  )
}
