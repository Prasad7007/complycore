import * as React from "react"
import * as LucideIcons from "lucide-react"
const { Trash2, X, File, FileText, Presentation } = LucideIcons as any
import { Navigate, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom"

import { MainLayout } from "@/components/layout/MainLayout"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"
import { documentsApi } from "@/lib/api"
import { UserSearchSelect } from "@/components/ui/user-search-select"

type UploadStage = "empty" | "uploading" | "ready"
type RoutingOption = "sme" | "marketing-ai"

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes)) return ""
  const mb = bytes / (1024 * 1024)
  return `${mb.toFixed(mb < 10 ? 2 : 1)} MB`
}

const fileTypeBg: Record<string, string> = {
  PDF: "bg-[#128BDA]/10",
  DOC: "bg-[#6B4EFF]/10",
  PPT: "bg-[#174199]/10",
}

const fileTypeLabel: Record<string, string> = {
  PDF: "PDF",
  DOC: "Word",
  PPT: "PowerPoint",
}

/** Must match backend ALLOWED_MARKETING_DOC_EXTENSIONS */
const ALLOWED_UPLOAD_EXTENSIONS = new Set([".pdf", ".doc", ".docx", ".ppt", ".pptx"])

function extensionLower(name: string): string {
  const i = name.lastIndexOf(".")
  return i >= 0 ? name.slice(i).toLowerCase() : ""
}

/** Same-origin path only — avoids open redirects via location.state. */
function sanitizeReturnTo(path: unknown): string | null {
  if (typeof path !== "string" || !path.startsWith("/")) return null
  if (path.startsWith("//") || path.includes("://")) return null
  return path
}

async function validateMarketingUploadFile(f: File): Promise<string | null> {
  const ext = extensionLower(f.name)
  if (!ALLOWED_UPLOAD_EXTENSIONS.has(ext)) {
    return "Only PDF, Word (.doc, .docx), and PowerPoint (.ppt, .pptx) files are allowed."
  }
  const buf = new Uint8Array(await f.slice(0, 8).arrayBuffer())
  if (buf.length < 8) return "File is empty or too small."
  if (ext === ".pdf") {
    const sig = String.fromCharCode(buf[0], buf[1], buf[2], buf[3])
    if (sig !== "%PDF") return "This file does not look like a valid PDF."
  } else if (ext === ".docx" || ext === ".pptx") {
    if (buf[0] !== 0x50 || buf[1] !== 0x4b || buf[2] !== 0x03 || buf[3] !== 0x04) {
      return "This file does not look like a valid .docx or .pptx file."
    }
  } else if (ext === ".doc" || ext === ".ppt") {
    const ole = [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]
    if (!ole.every((b, i) => buf[i] === b)) {
      return "This file does not look like a valid Word or PowerPoint 97–2003 document."
    }
  }
  return null
}

const fileTypeIcon: Record<string, React.ReactNode> = {
  PDF: <File className="h-6 w-6 text-[#128BDA]" strokeWidth={1.5} />,
  DOC: <FileText className="h-6 w-6 text-[#6B4EFF]" strokeWidth={1.5} />,
  PPT: <Presentation className="h-6 w-6 text-[#174199]" strokeWidth={1.5} />,
}

function FileTypeTile({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center gap-2">
      <div className={cn("grid h-12 w-12 place-items-center rounded-xl", fileTypeBg[label] ?? "bg-foreground/[0.04]")}>
        {fileTypeIcon[label] || <File className="h-6 w-6 text-muted-foreground" strokeWidth={1.5} />}
      </div>
      <div className="text-[11px] text-muted-foreground">{fileTypeLabel[label] ?? label}</div>
    </div>
  )
}

function getIconForFilename(name: string) {
  const ext = extensionLower(name)
  if (ext === ".pdf") return <File className="h-10 w-10 text-[#128BDA]" strokeWidth={1.5} />
  if (ext === ".doc" || ext === ".docx") return <FileText className="h-10 w-10 text-[#6B4EFF]" strokeWidth={1.5} />
  if (ext === ".ppt" || ext === ".pptx") return <Presentation className="h-10 w-10 text-[#174199]" strokeWidth={1.5} />
  return <File className="h-10 w-10 text-muted-foreground" strokeWidth={1.5} />
}

function RoutingCard({
  title,
  description,
  checked,
  onClick,
}: {
  title: string
  description: string
  checked: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-xl border bg-card p-4 text-left transition-colors",
        checked ? "border-[#1F4ED8] ring-1 ring-[#1F4ED8]/20" : "hover:bg-muted"
      )}
    >
      <div className="flex items-start gap-3">
      <span
  className={cn(
    "mt-0.5 flex shrink-0 items-center justify-center",
    "h-5 w-5 rounded-full",
    checked ? "border-2 border-gray-300" : "border-2 border-gray-300",
    "bg-card"
  )}
>
  {checked && (
    <span className="h-2.5 w-2.5 rounded-full bg-[#1F4ED8]" />
  )}
</span>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-foreground">{title}</div>
          <div className="mt-1 text-[11px] leading-4 text-muted-foreground">{description}</div>
        </div>
      </div>
    </button>
  )
}

export default function UploadDocumentPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const reuploadId = searchParams.get("reupload_id")

  const inputRef = React.useRef<HTMLInputElement | null>(null)
  const timerRef = React.useRef<number | null>(null)
  const uploadAbortRef = React.useRef<AbortController | null>(null)

  const [stage, setStage] = React.useState<UploadStage>("empty")
  const [file, setFile] = React.useState<File | null>(null)
  const [progress, setProgress] = React.useState(0)
  const [uploading, setUploading] = React.useState(false)
  const [uploadError, setUploadError] = React.useState<string | null>(null)

  const [routing, setRouting] = React.useState<RoutingOption>("sme")
  const [smeReviewer, setSmeReviewer] = React.useState("")
  const [docName, setDocName] = React.useState("")
  const [nextVersionLabel, setNextVersionLabel] = React.useState("")
  const [autoRoutingDest, setAutoRoutingDest] = React.useState<"SME" | "Compliance" | null>(null)

  const reset = React.useCallback(() => {
    uploadAbortRef.current?.abort()
    uploadAbortRef.current = null
    if (timerRef.current) window.clearInterval(timerRef.current)
    timerRef.current = null
    setUploading(false)
    setStage("empty")
    setFile(null)
    setProgress(0)
    setSmeReviewer("")
    if (inputRef.current) inputRef.current.value = ""
  }, [])

  const handleCancelClick = React.useCallback(() => {
    if (uploading) {
      reset()
      return
    }
    reset()
    if (!orgSlug?.trim()) {
      navigate("/pending-access", { replace: true })
      return
    }
    const fromState = sanitizeReturnTo((location.state as { returnTo?: string } | null)?.returnTo)
    if (fromState) {
      navigate(fromState, { replace: true })
      return
    }
    if (reuploadId) {
      navigate(`/orgs/${encodeURIComponent(orgSlug)}/validate-documents/detail/${reuploadId}`, {
        replace: true,
      })
      return
    }
    navigate(`/orgs/${encodeURIComponent(orgSlug)}/validate-documents`, { replace: true })
  }, [uploading, reset, location.state, navigate, reuploadId, orgSlug])

  React.useEffect(() => {
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current)
    }
  }, [])

  React.useEffect(() => {
    if (reuploadId && orgSlug) {
      documentsApi.get(orgSlug, reuploadId).then((res: any) => {
        if (res?.name) setDocName(res.name)
        const cl = res?.version_label
        let nv = "1.0"
        if (cl && typeof cl === "string" && cl.includes(".")) {
          const parts = cl.split(".")
          if (parts.length === 2) {
             const major = parseInt(parts[0], 10)
             const minor = parseInt(parts[1], 10)
             if (!isNaN(major) && !isNaN(minor)) {
               if (minor < 9) nv = `${major}.${minor+1}`
               else nv = `${major+1}.0`
             }
          }
        }
        setNextVersionLabel(nv)
      }).catch(() => {})

      documentsApi.getDocumentWorkflowSteps(orgSlug, reuploadId).then((steps: any[]) => {
        let dest: "SME" | "Compliance" | null = null
        for (let i = steps.length - 1; i >= 0; i--) {
          if (steps[i].action === "request_changes") {
             if (steps[i].previous_stage === "compliance_review") {
               dest = "Compliance"
             } else {
               dest = "SME"
             }
             break
          }
        }
        if (!dest) dest = "SME" // fallback
        setAutoRoutingDest(dest)
      }).catch(() => {})
    }
  }, [reuploadId, orgSlug])

  const beginUpload = React.useCallback((f: File) => {
    if (timerRef.current) window.clearInterval(timerRef.current)
    timerRef.current = null

    setFile(f)
    setStage("uploading")
    setProgress(0)

    // Fake upload progress (UI flow only)
    const start = performance.now()
    const durationMs = 2200
    timerRef.current = window.setInterval(() => {
      const t = Math.min(1, (performance.now() - start) / durationMs)
      const next = Math.round(t * 100)
      setProgress(next)
      if (t >= 1) {
        if (timerRef.current) window.clearInterval(timerRef.current)
        timerRef.current = null
        setStage("ready")
      }
    }, 60)
  }, [])

  const onPickedFile = React.useCallback(
    async (f: File | null) => {
      if (!f) return
      const err = await validateMarketingUploadFile(f)
      if (err) {
        setUploadError(err)
        if (inputRef.current) inputRef.current.value = ""
        return
      }
      setUploadError(null)
      beginUpload(f)
    },
    [beginUpload]
  )

  const canStart = stage === "ready" && !!file

  const handleStartReview = async () => {
    if (!file) return
    if (!orgSlug?.trim()) {
      navigate("/pending-access", { replace: true })
      return
    }

    uploadAbortRef.current?.abort()
    const ac = new AbortController()
    uploadAbortRef.current = ac

    try {
      setUploadError(null)
      setUploading(true)
      const formData = new FormData()
      formData.append("file", file)
      // Use filename as document name, default type is educational_content
      formData.append("document_name", file.name)
      formData.append("document_type", "educational_content")
      if (!reuploadId) {
        formData.append("routing", routing === "marketing-ai" ? "marketing" : "sme")
        // SME reviewer is optional - if not provided, all SMEs can claim
        if (routing === "sme" && smeReviewer) {
          formData.append("sme_reviewer_id", smeReviewer)
        }
      }

      const signal = ac.signal
      if (reuploadId) {
        const doc = await documentsApi.reupload(orgSlug, reuploadId, formData, { signal })
        navigate(`/orgs/${encodeURIComponent(orgSlug)}/validate-documents/detail/${doc.id}`)
      } else {
        const doc = await documentsApi.upload(orgSlug, formData, { signal })
        navigate(`/orgs/${encodeURIComponent(orgSlug)}/validate-documents/detail/${doc.id}`)
      }
    } catch (error: any) {
      if (error?.name === "AbortError") {
        return
      }
      console.error("Upload failed:", error)
      const errorMessage = error?.message || "Failed to upload document. Please try again."
      setUploadError(errorMessage)
      setUploading(false)
    } finally {
      if (uploadAbortRef.current === ac) uploadAbortRef.current = null
    }
  }

  if (!orgSlug?.trim()) {
    return <Navigate to="/pending-access" replace />
  }

  return (
    <MainLayout
      header={{
        breadcrumbs: [
          { label: "ComplyCore", to: `/orgs/${encodeURIComponent(orgSlug)}/dashboard/default` },
          { label: reuploadId ? "Upload New Version" : "Upload Document" },
        ],
      }}
    >
      <div className="space-y-6">
        <div>
          <div className="text-sm font-semibold text-foreground">
            {reuploadId ? "Upload New Version" : "Upload Document"}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {reuploadId 
              ? (docName ? `You are uploading Version ${nextVersionLabel} for ${docName}` : "Uploading a new version...")
              : "Upload marketing materials for compliance review"}
          </div>
        </div>

        {uploadError && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            {uploadError}
          </div>
        )}

        <Card className="rounded-xl border bg-card shadow-sm">
          <CardContent className="p-6">
            <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
              {/* Left: dropzone */}
              <div>
                <div
                  className={cn(
                    "relative rounded-2xl p-8 flex flex-col items-center justify-center text-center border-[3.1px] border-dashed",
                    "min-h-[520px]",
                    "bg-[#F0F9FF] border-[#38BDF8]",
                    "dark:bg-[#0B1220] dark:border-[#1D4ED8]"
                  )}
                  onDragOver={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                  }}
                  onDrop={async (e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    const f = e.dataTransfer.files?.[0]
                    await onPickedFile(f ?? null)
                  }}
                >
                 
                  <img
                    src="/upload/uploadPageDrag&dropIcon.svg"
                    alt="Upload"
                    className="h-24 w-auto"
                    draggable={false}
                  />

                  <div className="mt-6 text-2xl font-semibold text-foreground">
                    Drag and drop file here
                  </div>
                  <div className="mt-2 text-sm text-muted-foreground">
                    Supported: PDF, Word (.doc, .docx), PowerPoint (.ppt, .pptx). Or click{" "}
                    <button
                      type="button"
                      className="font-semibold text-[#1F4ED8] hover:underline"
                      onClick={() => inputRef.current?.click()}
                    >
                      Browse
                    </button>{" "}
                    from your computer
                  </div>

                  <input
                    ref={inputRef}
                    type="file"
                    accept=".pdf,.doc,.docx,.ppt,.pptx"
                    className="hidden"
                    onChange={(e) => void onPickedFile(e.target.files?.[0] ?? null)}
                  />

                  <div className="mt-8 flex items-center justify-center gap-10">
                    <FileTypeTile label="PDF" />
                    <FileTypeTile label="DOC" />
                    <FileTypeTile label="PPT" />
                  </div>
                </div>
              </div>

                {/* Right: settings */}
                <div className="flex flex-col gap-5">
                  {/* File card (step 2/3) */}
                  {file ? (
                    <div className="rounded-2xl  border bg-card p-2">
                      <div className="flex items-center gap-4">
                        <div className="grid h-24 w-24 shrink-0 place-items-center rounded-xl bg-muted">
                          {getIconForFilename(file.name)}
                        </div>
  
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-semibold text-foreground">{file.name}</div>
  
                          {stage === "uploading" ? (
                            <>
                              <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-foreground/10">
                                <div
                                  className="h-full rounded-full bg-[#1F4ED8] transition-[width]"
                                  style={{ width: `${progress}%` }}
                                />
                              </div>
                              <div className="mt-2 text-[11px] text-muted-foreground">
                                {formatBytes(file.size)} of {formatBytes(file.size)}
                              </div>
                            </>
                          ) : (
                            <>
                              <div className="mt-1 text-xs text-muted-foreground">
                                Ready for review
                              </div>
                              <div className="mt-2 text-[11px] text-muted-foreground">
                                {formatBytes(file.size)}
                              </div>
                            </>
                          )}
                        </div>
  
                        {stage === "uploading" ? (
                          <button
                            type="button"
                            className="grid h-9 w-9 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                            aria-label="Cancel upload"
                            onClick={reset}
                          >
                            <X className="h-4 w-4" />
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="grid h-9 w-9 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                            aria-label="Remove file"
                            onClick={reset}
                          >
                            <Trash2 className="h-5 w-5" />
                          </button>
                        )}
                      </div>
                    </div>
                  ) : null}
  
                  {!reuploadId ? (
                    <div>
                      <div className="text-sm font-semibold text-foreground">Document Routing</div>
  
                      <div className="mt-3 grid gap-3 sm:grid-cols-2">
                        <RoutingCard
                          title="Send to SME first"
                          description="Document goes to SME for expert review before marketing review"
                          checked={routing === "sme"}
                          onClick={() => setRouting("sme")}
                        />
                        <RoutingCard
                          title="Direct to Marketing with AI Analysis"
                          description="Skip SME review, document goes directly to marketing review with AI compliance analysis"
                          checked={routing === "marketing-ai"}
                          onClick={() => setRouting("marketing-ai")}
                        />
                      </div>
  
                      <div className="mt-5 space-y-2">
                        <Label className="text-xs font-semibold" htmlFor="smeReviewer">
                          Assign SME Reviewer (Optional)
                        </Label>
                        <div className="text-[11px] text-muted-foreground mb-2">
                          If not assigned, all SMEs will see the "Claim Review" option
                        </div>
                        <div className="relative">
                          <UserSearchSelect
                            role="sme"
                            value={smeReviewer}
                            onChange={setSmeReviewer}
                            disabled={routing !== "sme"}
                            placeholder="Search SME reviewers..."
                            defaultLabel="All SMEs can claim"
                          />
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div className="text-sm font-semibold text-foreground">Document Routing</div>
                      <div className="mt-3 rounded-xl border bg-muted/30 p-4">
                        <div className="flex items-start gap-3">
                          <div className="min-w-0">
                            <div className="text-xs font-semibold text-foreground">
                              {autoRoutingDest === "Compliance" ? "AI Analysis & Marketing Review" : "Automatic Routing"}
                            </div>
                            <div className="mt-1 text-[11px] leading-4 text-muted-foreground">
                              {autoRoutingDest === "Compliance"
                                ? "This document will run AI compliance analysis and remain in Marketing Review, so you can review findings before manually sending it back to Compliance."
                                : `This document will be automatically routed to ${autoRoutingDest || "SME"} for review. AI compliance analysis will run after the reviewer approves the revised document.`
                              }
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                <div className="mt-auto flex items-center justify-end gap-3 pt-2">
                  <Button
                    type="button"
                    variant="outline"
                    className="h-10 px-6"
                    onClick={handleCancelClick}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    className="h-10 rounded-md bg-[#128BDA] px-8 font-semibold text-white hover:bg-[#128BDA]/90"
                    disabled={!canStart || uploading}
                    onClick={handleStartReview}
                  >
                    {uploading ? "Uploading..." : "Upload"}
                  </Button>
                </div>

                {/* (Optional) Keep layout similar even without file */}
                {!file ? (
                  <div className="hidden">
                    <Input />
                  </div>
                ) : null}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </MainLayout>
  )
}
