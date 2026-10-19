import { formatFastApiDetail } from "./normalize-api-error"
import { logApiError, logUploadError, logFrontendError, ErrorCategory } from "./error-logger"

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1"
export const apiFetch = apiRequest

/** API path prefix for tenant-scoped resources (documents, findings, review comments under same org). */
export function tenantApiPrefix(orgSlug: string): string {
  return `/orgs/${encodeURIComponent(orgSlug)}`
}

// In-memory /users/me cache: avoids redundant calls from Header, Sidebar,
// document detail, etc. that all fire on the same render cycle.
const USER_ME_CACHE_TTL_MS = 60_000
let _userMeCache: { data: unknown; expiresAt: number; inflight: Promise<unknown> | null } = {
  data: null,
  expiresAt: 0,
  inflight: null,
}

function getCachedUserMe(): Promise<unknown> {
  if (_userMeCache.data && Date.now() < _userMeCache.expiresAt) {
    return Promise.resolve(_userMeCache.data)
  }
  if (_userMeCache.inflight) return _userMeCache.inflight
  _userMeCache.inflight = apiRequest<unknown>("/users/me").then((data) => {
    _userMeCache = { data, expiresAt: Date.now() + USER_ME_CACHE_TTL_MS, inflight: null }
    return data
  }).catch((err) => {
    _userMeCache.inflight = null
    throw err
  })
  return _userMeCache.inflight
}

export function invalidateUserMeCache() {
  _userMeCache = { data: null, expiresAt: 0, inflight: null }
}

/** Bypass /users/me cache — use after login or when onboarding state must be authoritative. */
export async function fetchUserMeFresh<T = unknown>(): Promise<T> {
  invalidateUserMeCache()
  return apiRequest<T>("/users/me")
}

function formatUploadQuotaError(detail: unknown): string {
  if (detail && typeof detail === "object" && "code" in detail) {
    const code = String((detail as { code?: unknown }).code || "").trim()
    if (code === "ORG_UPLOAD_QUOTA_EXCEEDED") {
      const message = typeof (detail as { message?: unknown }).message === "string"
        ? String((detail as { message?: string }).message).trim()
        : ""
      return (
        message ||
        "This organization has reached its upload limit. Please contact your platform owner."
      )
    }
  }
  return formatFastApiDetail(detail)
}

export type DocumentPreviewResponse = {
  url: string
  file_name: string
  mime: string
  original_url?: string
  original_file_name?: string
  original_mime?: string
  preview_fallback?: boolean
}

export type UploadQuotaState = {
  effective_quota: {
    organization_id: string
    organization_slug?: string
    organization_created_at: string
    quota_settings_id: string | null
    quota_enabled: boolean
    upload_limit_count: number
    upload_limit_bytes: number
    rolling_window_days: number
    rollout_starts_at: string
    updated_at: string | null
    updated_by: string | null
    bypass_active: boolean
    bypass_reason: string | null
    default_values: {
      quota_enabled: boolean
      upload_limit_count: number
      upload_limit_bytes: number
      rollout_starts_at: string
    }
  }
  usage: {
    organization_id: string
    organization_slug?: string
    as_of: string
    window_start: string | null
    window_days: number
    rollout_active: boolean
    bypass_active: boolean
    upload_count_used: number
    upload_bytes_used: number
  }
  enforcement: {
    bypass_active: boolean
    quota_enabled: boolean
    rollout_active: boolean
    should_enforce: boolean
  }
  remaining: {
    upload_count_remaining: number
    upload_bytes_remaining: number
  }
}

let activeRefreshPromise: Promise<boolean> | null = null

async function attemptTokenRefresh(): Promise<boolean> {
  if (activeRefreshPromise) {
    return activeRefreshPromise
  }

  activeRefreshPromise = (async () => {
    try {
      const refreshRes = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" }
      })
      return refreshRes.ok
    } catch (e) {
      return false
    } finally {
      activeRefreshPromise = null
    }
  })()

  return activeRefreshPromise
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit & { _retry?: boolean } = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`

  try {
    console.log(`[API] Requesting: ${options.method || "GET"} ${endpoint}`)
    
    const response = await fetch(url, {
      ...options,
      // httpOnly session cookie carries auth; browser attaches it when same-origin
      // or when CORS allow_credentials + an exact allow-origin match is configured.
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }))
      
      // If 401, attempt to refresh token once
      if (
        response.status === 401 && 
        !options._retry && 
        endpoint !== "/auth/refresh" && 
        endpoint !== "/auth/login" && 
        endpoint !== "/auth/logout"
      ) {
        const success = await attemptTokenRefresh()
        if (success) {
          options._retry = true
          return apiRequest<T>(endpoint, options)
        }
      }

      if (response.status === 401) {
        logApiError(
          "Authentication required",
          endpoint,
          options.method,
          response.status,
          { detail: (error as any).detail }
        )
        throw new Error("Authentication required. Please login first.")
      }
      const msg = formatFastApiDetail((error as { detail?: unknown }).detail)
      logApiError(
        msg || `HTTP ${response.status}`,
        endpoint,
        options.method,
        response.status,
        { detail: (error as any).detail }
      )
      throw new Error(msg || `HTTP error! status: ${response.status}`)
    }

    console.log(`[API] Success: ${options.method || "GET"} ${endpoint}`)
    return response.json()
  } catch (error: any) {
    if (error instanceof TypeError && error.message === "Failed to fetch") {
      logFrontendError(
        new Error("Cannot connect to server"),
        ErrorCategory.NETWORK,
        `API request to ${endpoint}`,
        undefined,
        { endpoint, method: options.method || "GET" }
      )
      throw new Error("Unable to connect to the server. Please check your internet connection or try again later.")
    }
    console.error(`[API] Error: ${options.method || "GET"} ${endpoint}`, error)
    throw error
  }
}

export const documentsApi = {
  list: (orgSlug: string) => apiRequest<Array<any>>(`${tenantApiPrefix(orgSlug)}/documents`),
  get: (orgSlug: string, docId: string) => apiRequest<any>(`${tenantApiPrefix(orgSlug)}/documents/${docId}`),
  getUploadQuota: (orgSlug: string) =>
    apiRequest<UploadQuotaState>(`${tenantApiPrefix(orgSlug)}/documents/upload-quota`),
  upload: async (orgSlug: string, formData: FormData, opts?: { signal?: AbortSignal }) => {
    const fileName = (formData.get("file") as File)?.name || "unknown"
    const fileSize = (formData.get("file") as File)?.size || 0
    
    console.log(`[UPLOAD] Starting upload: ${fileName} (${fileSize} bytes)`)
    
    try {
      const response = await fetch(`${API_BASE_URL}${tenantApiPrefix(orgSlug)}/documents/upload`, {
        method: "POST",
        credentials: "include",
        body: formData,
        signal: opts?.signal,
      })
      
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        if (response.status === 401 && !opts?._retry) {
          const success = await attemptTokenRefresh()
          if (success) {
            return documentsApi.upload(orgSlug, formData, { ...opts, _retry: true })
          }
        }
        if (response.status === 401) {
          logUploadError(
            "Authentication required",
            "upload_document",
            fileName,
            fileSize
          )
          throw new Error("Authentication required. Please login first.")
        }
        const msg = formatUploadQuotaError((error as { detail?: unknown }).detail)
        logUploadError(
          msg || `HTTP ${response.status}`,
          "upload_document",
          fileName,
          fileSize,
          undefined,
          { statusCode: response.status, detail: (error as any).detail }
        )
        throw new Error(msg || `HTTP error! status: ${response.status}`)
      }
      
      console.log(`[UPLOAD] Success: ${fileName}`)
      return response.json()
    } catch (error: any) {
      if (error?.name === "AbortError") throw error
      if (error instanceof TypeError && error.message === "Failed to fetch") {
        logUploadError(
          "Cannot connect to server",
          "upload_document",
          fileName,
          fileSize,
          undefined,
          { cause: "network_error" }
        )
        throw new Error("Unable to connect to the server. Please check your internet connection or try again later.")
      }
      console.error(`[UPLOAD] Error uploading ${fileName}:`, error)
      throw error
    }
  },
  reupload: async (orgSlug: string, docId: string, formData: FormData, opts?: { signal?: AbortSignal }) => {
    const fileName = (formData.get("file") as File)?.name || "unknown"
    const fileSize = (formData.get("file") as File)?.size || 0
    
    console.log(`[REUPLOAD] Starting reupload for doc ${docId}: ${fileName}`)
    
    try {
      const response = await fetch(`${API_BASE_URL}${tenantApiPrefix(orgSlug)}/documents/${docId}/reupload`, {
        method: "POST",
        credentials: "include",
        body: formData,
        signal: opts?.signal,
      })
      
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        if (response.status === 401 && !opts?._retry) {
          const success = await attemptTokenRefresh()
          if (success) {
            return documentsApi.reupload(orgSlug, docId, formData, { ...opts, _retry: true })
          }
        }
        if (response.status === 401) {
          logUploadError(
            "Authentication required",
            "reupload_document",
            fileName,
            fileSize,
            undefined,
            { documentId: docId }
          )
          throw new Error("Authentication required. Please login first.")
        }
        const msg = formatUploadQuotaError((error as { detail?: unknown }).detail)
        logUploadError(
          msg || `HTTP ${response.status}`,
          "reupload_document",
          fileName,
          fileSize,
          undefined,
          { documentId: docId, statusCode: response.status }
        )
        throw new Error(msg || `HTTP error! status: ${response.status}`)
      }
      
      console.log(`[REUPLOAD] Success: ${fileName} for doc ${docId}`)
      return response.json()
    } catch (error: any) {
      if (error?.name === "AbortError") throw error
      if (error instanceof TypeError && error.message === "Failed to fetch") {
        logUploadError(
          "Cannot connect to server",
          "reupload_document",
          fileName,
          fileSize,
          undefined,
          { documentId: docId, cause: "network_error" }
        )
        throw new Error("Unable to connect to the server. Please check your internet connection or try again later.")
      }
      console.error(`[REUPLOAD] Error reuploading ${fileName} for doc ${docId}:`, error)
      throw error
    }
  },
  claim: (orgSlug: string, docId: string) =>
    apiRequest<{ ok: boolean }>(`${tenantApiPrefix(orgSlug)}/documents/${docId}/claim`, { method: "POST" }),
  smeApprove: (orgSlug: string, docId: string) =>
    apiRequest<{ ok: boolean }>(`${tenantApiPrefix(orgSlug)}/documents/${docId}/sme-approve`, { method: "POST" }),
  smeReject: async (orgSlug: string, docId: string, comment?: string) => {
    const params = new URLSearchParams()
    if (comment) params.append("comment", comment)
    const base = `${tenantApiPrefix(orgSlug)}/documents/${docId}/sme-reject`
    const url = `${base}${params.toString() ? `?${params.toString()}` : ""}`
    return apiRequest<{ ok: boolean }>(url, { method: "POST" })
  },
  smeRequestChanges: async (orgSlug: string, docId: string, comment?: string) => {
    const params = new URLSearchParams()
    if (comment) params.append("comment", comment)
    const base = `${tenantApiPrefix(orgSlug)}/documents/${docId}/sme-request-changes`
    const url = `${base}${params.toString() ? `?${params.toString()}` : ""}`
    return apiRequest<{ ok: boolean }>(url, { method: "POST" })
  },
  marketingApprove: async (orgSlug: string, docId: string, complianceReviewerId?: string) => {
    const params = new URLSearchParams()
    if (complianceReviewerId) params.append("compliance_reviewer_id", complianceReviewerId)
    const base = `${tenantApiPrefix(orgSlug)}/documents/${docId}/marketing-approve`
    const url = `${base}${params.toString() ? `?${params.toString()}` : ""}`
    return apiRequest<{ ok: boolean }>(url, { method: "POST" })
  },
  complianceApprove: async (orgSlug: string, docId: string, lock: boolean = true) => {
    const url = `${tenantApiPrefix(orgSlug)}/documents/${docId}/compliance-approve?lock=${lock}`
    return apiRequest<{ ok: boolean }>(url, { method: "POST" })
  },
  complianceReject: async (orgSlug: string, docId: string, comment?: string) => {
    const params = new URLSearchParams()
    if (comment) params.append("comment", comment)
    const base = `${tenantApiPrefix(orgSlug)}/documents/${docId}/compliance-reject`
    const url = `${base}${params.toString() ? `?${params.toString()}` : ""}`
    return apiRequest<{ ok: boolean }>(url, { method: "POST" })
  },
  complianceRequestChanges: async (orgSlug: string, docId: string, comment?: string) => {
    const params = new URLSearchParams()
    if (comment) params.append("comment", comment)
    const base = `${tenantApiPrefix(orgSlug)}/documents/${docId}/compliance-request-changes`
    const url = `${base}${params.toString() ? `?${params.toString()}` : ""}`
    return apiRequest<{ ok: boolean }>(url, { method: "POST" })
  },
  publish: (orgSlug: string, docId: string) =>
    apiRequest<{ ok: boolean }>(`${tenantApiPrefix(orgSlug)}/documents/${docId}/publish`, { method: "POST" }),
  getReview: (orgSlug: string, docId: string, versionId?: string) => {
    const base = `${tenantApiPrefix(orgSlug)}/documents/${docId}/review`
    const url = versionId ? `${base}?version_id=${encodeURIComponent(versionId)}` : base
    return apiRequest<any>(url)
  },
  /** Re-run AI compliance analysis (e.g. after a failure). */
  triggerAiAnalysis: (orgSlug: string, docId: string) =>
    apiRequest<{ ok: boolean; queued?: boolean }>(`${tenantApiPrefix(orgSlug)}/documents/${docId}/analyze`, {
      method: "POST",
    }),
  getFile: (orgSlug: string, docId: string) =>
    apiRequest<DocumentPreviewResponse>(`${tenantApiPrefix(orgSlug)}/documents/${docId}/file`),
  /** Presigned URL for annotated (or fallback raw) document file. */
  getAnnotatedFile: (orgSlug: string, docId: string, versionId?: string) => {
    const params = new URLSearchParams()
    if (versionId) params.append("version_id", versionId)
    const url = `${tenantApiPrefix(orgSlug)}/documents/${docId}/annotated_file${params.toString() ? `?${params.toString()}` : ""}`
    return apiRequest<DocumentPreviewResponse>(url)
  },
  /** Presigned S3 URL for a specific version (audit trail / previews). */
  getVersionFileUrl: (orgSlug: string, versionId: string, download?: boolean) =>
    apiRequest<DocumentPreviewResponse>(
      `${tenantApiPrefix(orgSlug)}/documents/versions/${versionId}/file-url${download ? "?download=true" : ""}`
    ),
  getUserInfo: () => getCachedUserMe() as Promise<any>,
  assign: async (orgSlug: string, docId: string, assigneeId?: string, assignedRole?: string) => {
    const params = new URLSearchParams()
    if (assigneeId) params.append("assignee_id", assigneeId)
    if (assignedRole) params.append("assigned_role", assignedRole)
    const base = `${tenantApiPrefix(orgSlug)}/documents/${docId}/assign`
    const url = `${base}${params.toString() ? `?${params.toString()}` : ""}`
    return apiRequest<{ ok: boolean }>(url, { method: "POST" })
  },
  getDocumentComments: (orgSlug: string, docId: string) =>
    apiRequest<Array<any>>(`${tenantApiPrefix(orgSlug)}/documents/${docId}/comments`),
  getDocumentWorkflowSteps: (orgSlug: string, docId: string) =>
    apiRequest<Array<any>>(`${tenantApiPrefix(orgSlug)}/documents/${docId}/workflow-steps`),
  getDocumentUnifiedAuditTrail: (orgSlug: string, docId: string) =>
    apiRequest<{ events: Array<any>; version_groups: Array<any> }>(
      `${tenantApiPrefix(orgSlug)}/documents/${docId}/audit-trail-unified`
    ),
  /**
   * Same-origin SSE URL. Auth flows through the httpOnly session cookie; consumers
   * must construct ``new EventSource(url, { withCredentials: true })``.
   */
  analysisStreamUrl: (orgSlug: string, docId: string) =>
    `${API_BASE_URL}${tenantApiPrefix(orgSlug)}/documents/${docId}/analysis-stream`,
}

export const usersApi = {
  list: (role?: string, query?: string) => {
    const params = new URLSearchParams()
    if (role) params.append("role", role)
    if (query) params.append("query", query)
    const queryString = params.toString() ? `?${params.toString()}` : ""
    return apiRequest<Array<any>>(`/users${queryString}`)
  },
  getMe: () => getCachedUserMe() as Promise<any>,
}

export type OrganizationBootstrapPayload = {
  organization_name: string
  organization_slug: string
  superadmin_email: string
  superadmin_full_name: string
  superadmin_password: string
  superadmin_department: string
  superadmin_phone?: string
}

export type OrganizationBootstrapResult = {
  organization_id: string
  organization_slug: string
  superadmin_user_id: string
  superadmin_email: string
  message: string
}

export type OrganizationListItem = {
  id: string
  name: string
  slug: string
  status: string
  created_at: string
}

export type OrganizationUploadQuotaDefaults = {
  quota_enabled: boolean
  upload_limit_count: number
  upload_limit_bytes: number
  rollout_starts_at: string
}

export type OrganizationUploadQuotaSettingsResponse = {
  organization_id: string
  organization_slug: string
  organization_name: string
  org_created_at: string
  quota_settings_id: string | null
  quota_enabled: boolean
  upload_limit_count: number
  upload_limit_bytes: number
  rollout_starts_at: string
  rolling_window_days: number
  defaults: OrganizationUploadQuotaDefaults
  effective_quota: {
    quota_enabled: boolean
    upload_limit_count: number
    upload_limit_bytes: number
    rollout_starts_at: string
    rolling_window_days: number
  }
  updated_at: string | null
  updated_by: string | null
  bypass_active: boolean
  bypass_reason: string | null
}

export type OrganizationUploadQuotaSettingsUpdate = {
  quota_enabled: boolean
  upload_limit_count: number
  upload_limit_bytes: number
  rollout_starts_at: string
}

export type SuperAdminResponse = {
  user_id: string
  email: string
  full_name: string
  department: string
  phone_number?: string | null
  created_at: string
  is_active: boolean
}

export const organizationsApi = {
  list: () => apiRequest<OrganizationListItem[]>("/organizations"),
  /** Owner only: all department names from DB (catalog + user_profiles). */
  listDepartments: () => apiRequest<string[]>("/organizations/departments"),
  getOrganizationUploadQuotaSettings: (organizationId: string) =>
    apiRequest<OrganizationUploadQuotaSettingsResponse>(
      `/organizations/${encodeURIComponent(organizationId)}/upload-quota`
    ),
  updateOrganizationUploadQuotaSettings: (
    organizationId: string,
    payload: OrganizationUploadQuotaSettingsUpdate
  ) =>
    apiRequest<OrganizationUploadQuotaSettingsResponse>(
      `/organizations/${encodeURIComponent(organizationId)}/upload-quota`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      }
    ),
  resetOrganizationUploadQuotaSettings: (organizationId: string) =>
    apiRequest<OrganizationUploadQuotaSettingsResponse>(
      `/organizations/${encodeURIComponent(organizationId)}/upload-quota/reset`,
      {
        method: "POST",
      }
    ),
  bootstrap: (payload: OrganizationBootstrapPayload) =>
    apiRequest<OrganizationBootstrapResult>("/organizations/bootstrap", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listSuperAdmins: (organizationId: string) =>
    apiRequest<SuperAdminResponse[]>(`/organizations/${encodeURIComponent(organizationId)}/superadmins`),
  createSuperAdmin: (
    organizationId: string,
    payload: { email: string; full_name: string; password: string; phone_number?: string }
  ) =>
    apiRequest<SuperAdminResponse>(`/organizations/${encodeURIComponent(organizationId)}/superadmins`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteSuperAdmin: (organizationId: string, userId: string) =>
    apiRequest<{ message: string }>(
      `/organizations/${encodeURIComponent(organizationId)}/superadmins/${encodeURIComponent(userId)}`,
      {
        method: "DELETE",
      }
    ),
  reactivateSuperAdmin: (organizationId: string, userId: string) =>
    apiRequest<{ message: string }>(
      `/organizations/${encodeURIComponent(organizationId)}/superadmins/${encodeURIComponent(userId)}/reactivate`,
      {
        method: "POST",
      }
    ),
}

export const workflowsApi = {
  get: (orgSlug: string, reviewId: string) =>
    apiRequest<any>(`${tenantApiPrefix(orgSlug)}/workflows/${reviewId}`),
  transition: (orgSlug: string, reviewId: string, action: string, comment?: string, assignTo?: string) =>
    apiRequest<any>(`${tenantApiPrefix(orgSlug)}/workflows/${reviewId}/transition`, {
      method: "POST",
      body: JSON.stringify({ action, comment, assign_to: assignTo }),
    }),
}

// General comments on a review (the Comments & Discussion section)
export const reviewsApi = {
  getComments: (orgSlug: string, reviewId: string) =>
    apiRequest<Array<any>>(`${tenantApiPrefix(orgSlug)}/reviews/${reviewId}/comments`),
  addComment: (orgSlug: string, reviewId: string, content: string, mentionedUserIds?: string[]) =>
    apiRequest<any>(`${tenantApiPrefix(orgSlug)}/reviews/${reviewId}/comments`, {
      method: "POST",
      body: JSON.stringify({
        content,
        ...(mentionedUserIds?.length ? { mentioned_user_ids: mentionedUserIds } : {}),
      }),
    }),
  /** Same-origin SSE URL; consumers must use ``EventSource(url, { withCredentials: true })``. */
  commentsStreamUrl: (orgSlug: string, reviewId: string) =>
    `${API_BASE_URL}${tenantApiPrefix(orgSlug)}/reviews/${reviewId}/comments/stream`,
}

export const findingsApi = {
  getFindings: (orgSlug: string, reviewId: string) =>
    apiRequest<Array<any>>(`${tenantApiPrefix(orgSlug)}/findings/reviews/${reviewId}/findings`),
  acceptFinding: (orgSlug: string, findingId: string, suggestionId?: string) =>
    apiRequest<any>(`${tenantApiPrefix(orgSlug)}/findings/${findingId}/status`, {
      method: "PUT",
      body: JSON.stringify({
        status: "accepted",
        ...(suggestionId ? { suggestion_id: suggestionId } : {}),
      }),
    }),
  rejectFinding: (orgSlug: string, findingId: string, reason?: string) =>
    apiRequest<any>(`${tenantApiPrefix(orgSlug)}/findings/${findingId}/status`, {
      method: "PUT",
      body: JSON.stringify({ status: "rejected", reason }),
    }),
  dismissFinding: (orgSlug: string, findingId: string, reason?: string) =>
    apiRequest<any>(`${tenantApiPrefix(orgSlug)}/findings/${findingId}/status`, {
      method: "PUT",
      body: JSON.stringify({ status: "dismissed", reason }),
    }),
  addComment: (orgSlug: string, findingId: string, content: string) =>
    apiRequest<any>(`${tenantApiPrefix(orgSlug)}/findings/${findingId}/comments`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  addSuggestion: (orgSlug: string, findingId: string, text: string) =>
    apiRequest<any>(`${tenantApiPrefix(orgSlug)}/findings/${findingId}/suggestions`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  getComments: (orgSlug: string, findingId: string) =>
    apiRequest<Array<any>>(`${tenantApiPrefix(orgSlug)}/findings/${findingId}/comments`),
  getSuggestions: (orgSlug: string, findingId: string) =>
    apiRequest<Array<any>>(`${tenantApiPrefix(orgSlug)}/findings/${findingId}/suggestions`),
  editSuggestion: (orgSlug: string, findingId: string, suggestionId: string, text: string) =>
    apiRequest<any>(`${tenantApiPrefix(orgSlug)}/findings/${findingId}/suggestions/${suggestionId}`, {
      method: "PUT",
      body: JSON.stringify({ text }),
    }),
}

/** Dashboard StatCards (from /audit-trail/dashboard-stats) */
export type DashboardStats = {
  highRiskFlags: number
  linkedinPostsMonitored: number
  documentsUnderReview: number
  pendingActions: number
  trends: {
    linkedinPostsMonitored: string | null
    documentsUnderReview: string | null
    pendingActions: string | null
    highRiskFlags: string | null
  }
}

export type StatCardInfo = {
  title: string
  desc: string
  calc: string
}

export type StatSeriesPoint = {
  label: string
  value: number
  date: string
}

export type StatCardSeries = {
  bucket: "day" | "month"
  points: StatSeriesPoint[]
}

export type DashboardStatCard = {
  id: string
  label: string
  value: string
  unit?: string | null
  description: string
  info?: StatCardInfo | null
  trend?: {
    display?: string | null
    direction: "up" | "down" | "neutral"
  } | null
  series?: StatCardSeries | null
}

export type DashboardStatCardsResponse = {
  role: string
  period: string
  cards: DashboardStatCard[]
}

export type ReviewStatusStats = {
  totalDocuments: number
  marketingReview: number
  complianceReview: number
  pendingSmeReview: number
  approved: number
  rejected: number
  published: number
  notStarted: number
}

/** Dashboard recent activity (audit events + AI findings), last ~30 days */
export type RecentActivityFeedItem = {
  id: string
  feedSource: "audit" | "finding"
  eventType: string
  createdAt: string
  reviewId: string
  contentType: string
  documentId: string | null
  socialPostId: string | null
  contentLabel: string
  documentCode: string | null
  description: string | null
  title: string | null
  detailText: string | null
  ruleCode: string | null
  ruleName: string | null
  findingCode: string | null
  riskLevel: string | null
  userName: string | null
  userRole: string | null
  isAi: boolean
  workflowStage: string | null
  versionId: string | null
}

export type AuditTrailRow = {
  step: string
  reviewId: string
  document: string
  workflowStage: string
  status: string
  riskLevel: "High" | "Medium" | "Low"
  action: string
  performedBy: string
  versions: string
  latestVersion?: string
  versionCount?: number
  notes: string
  timestamp?: string | null
  documentId?: string
  department?: string
  roles?: string[]
}

export type ReviewVersion = {
  id: string
  label: string
  uploadedAt: string | null
  status: string
  changeSummary: string
  text: string
  reviewId?: string
}

// Audit trail (all calls require org slug — API is mounted under `/orgs/{org_slug}`)
export const auditApi = {
  /** Global audit trail — one row per document review (used on Audit Trail page) */
  getGlobalAuditTrail: (orgSlug: string) =>
    apiRequest<Array<AuditTrailRow>>(`${tenantApiPrefix(orgSlug)}/audit-trail`),
  /** Merged recent audit events and findings for the dashboard feed */
  getRecentActivity: (orgSlug: string, limit = 30) =>
    apiRequest<{ items: RecentActivityFeedItem[] }>(
      `${tenantApiPrefix(orgSlug)}/audit-trail/recent-activity?limit=${limit}`
    ),
  getDashboardStats: (orgSlug: string, period: string = "month", opts?: { dateFrom?: string; dateTo?: string }) => {
    const params = new URLSearchParams()
    params.set("period", period)
    if (opts?.dateFrom) params.set("date_from", opts.dateFrom)
    if (opts?.dateTo) params.set("date_to", opts.dateTo)
    return apiRequest<DashboardStats>(
      `${tenantApiPrefix(orgSlug)}/audit-trail/dashboard-stats?${params.toString()}`
    )
  },
  getDashboardStatCards: (
    orgSlug: string,
    role: "marketing" | "sme" | "compliance" | "superadmin",
    period: string = "month",
    opts?: { dateFrom?: string; dateTo?: string }
  ) => {
    const params = new URLSearchParams()
    params.set("role", role)
    params.set("period", period)
    if (opts?.dateFrom) params.set("date_from", opts.dateFrom)
    if (opts?.dateTo) params.set("date_to", opts.dateTo)
    return apiRequest<DashboardStatCardsResponse>(
      `${tenantApiPrefix(orgSlug)}/audit-trail/stat-cards?${params.toString()}`
    )
  },
  getReviewStatusStats: (
    orgSlug: string,
    period: string = "all",
    opts?: { dateFrom?: string; dateTo?: string }
  ) => {
    const params = new URLSearchParams()
    params.set("period", period)
    if (opts?.dateFrom) params.set("date_from", opts.dateFrom)
    if (opts?.dateTo) params.set("date_to", opts.dateTo)
    return apiRequest<ReviewStatusStats>(
      `${tenantApiPrefix(orgSlug)}/audit-trail/review-status-stats?${params.toString()}`
    )
  },
  getReviewVersions: (orgSlug: string, reviewId: string) =>
    apiRequest<{ reviewId: string; versions: ReviewVersion[] }>(
      `${tenantApiPrefix(orgSlug)}/reviews/${reviewId}/versions`
    ),
  /** Per-review workflow step history (used in expanded row of Audit Trail page) */
  getAuditTrail: (orgSlug: string, reviewId: string) =>
    apiRequest<Array<any>>(`${tenantApiPrefix(orgSlug)}/reviews/${reviewId}/audit-trail`),
  getUnifiedAuditTrail: (orgSlug: string, reviewId: string) =>
    apiRequest<{ events: Array<any> }>(
      `${tenantApiPrefix(orgSlug)}/reviews/${reviewId}/audit-trail-unified`
    ),
}

export const authApi = {
  signup: (payload: {
    email: string
    password: string
    full_name: string
    avatar_url?: string
  }) =>
    apiRequest<any>("/auth/signup", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

     // ✅ ADD THIS HERE
  checkEmail: (email: string) =>
    apiRequest<any>(`/auth/check-email?email=${encodeURIComponent(email)}`),

  login: async (email: string, password: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email, password }),
      })
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        const msg = formatFastApiDetail((error as { detail?: unknown }).detail)
        throw new Error(msg || `HTTP error! status: ${response.status}`)
      }
      const data = await response.json()
      // Session token (if returned) is now set by the server as an httpOnly cookie;
      // we still invalidate the user cache so the next /users/me reflects the new session.
      if (data?.token_in_cookie) {
        invalidateUserMeCache()
      }
      return data
    } catch (error: any) {
      if (error instanceof TypeError && error.message === "Failed to fetch") {
        throw new Error("Unable to connect to the server. Please check your internet connection or try again later.")
      }
      throw error
    }
  },
  /**
   * Retained for API compatibility. The server now issues the demo session via an
   * httpOnly cookie on ``/auth/verify-otp``; this method only invalidates the
   * user cache so callers that used the old localStorage path still trigger a
   * fresh ``/users/me``.
   */
  setDemoToken: (_token?: string) => {
    void _token
    invalidateUserMeCache()
  },
  verifyOtp: async (email: string, otp: string, session: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/verify-otp`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, otp, session }),
      })
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        const msg = formatFastApiDetail((error as { detail?: unknown }).detail)
        throw new Error(msg || `HTTP error! status: ${response.status}`)
      }
      const data = await response.json()
      if (data?.token_in_cookie) {
        invalidateUserMeCache()
      }
      return data
    } catch (error: any) {
      if (error instanceof TypeError && error.message === "Failed to fetch") {
        throw new Error("Unable to connect to the server. Please check your internet connection or try again later.")
      }
      throw error
    }
  },
  resendOtp: (email: string, session: string) =>
    apiRequest<any>("/auth/resend-otp", {
      method: "POST",
      body: JSON.stringify({ email, session }),
    }),
  verifyEmail: async (email: string, code: string, password?: string) => {
    const response = await fetch(`${API_BASE_URL}/auth/verify-email`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        code,
        ...(password ? { password } : {}),
      }),
    })
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }))
      const msg = formatFastApiDetail((error as { detail?: unknown }).detail)
      throw new Error(msg || `HTTP error! status: ${response.status}`)
    }
    const data = await response.json()
    if (data?.token_in_cookie) {
      invalidateUserMeCache()
    }
    return data
  },
  resendCode: async (email: string) => {
    return apiRequest<any>("/auth/resend-code", {
      method: "POST",
      body: JSON.stringify({ email }),
    })
  },
  forgotPassword: async (email: string) => {
    return apiRequest<any>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    })
  },
  confirmForgotPassword: async (email: string, code: string, newPassword: string) => {
    return apiRequest<any>("/auth/confirm-forgot-password", {
      method: "POST",
      body: JSON.stringify({ email, code, new_password: newPassword }),
    })
  },
  changePassword: async (oldPassword: string, newPassword: string, opts?: { _retry?: boolean }) => {
    const response = await fetch(`${API_BASE_URL}/auth/change-password`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }))
      if (response.status === 401 && !opts?._retry) {
        const success = await attemptTokenRefresh()
        if (success) {
          return authApi.changePassword(oldPassword, newPassword, { _retry: true })
        }
      }
      throw new Error(error.detail || `HTTP error! status: ${response.status}`)
    }
    return response.json()
  },
  /** Server clears the session cookie and (for non-demo) revokes Cognito tokens. */
  logout: async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/logout`, {
        method: "POST",
        credentials: "include",
      })
      invalidateUserMeCache()
      if (!response.ok) {
        // Even on server error, the client should treat itself as logged out;
        // the cookie has been cleared by the server in the happy path and the
        // user can re-authenticate.
        return { ok: false }
      }
      return await response.json().catch(() => ({ ok: true }))
    } catch {
      invalidateUserMeCache()
      return { ok: false }
    }
  },
}

export type NotificationItem = {
  id: string
  user_id: string
  type: string
  title: string
  message: string | null
  reference_type: string | null
  reference_id: string | null
  is_read: boolean
  created_at: string
}

export const notificationsApi = {
  list: () => apiRequest<NotificationItem[]>("/notifications"),
  markRead: (notificationId: string) =>
    apiRequest<any>(`/notifications/${notificationId}/read`, { method: "PUT" }),
  markAllRead: () => apiRequest<any>("/notifications/mark-all-read", { method: "POST" }),
  /** Same-origin SSE URL; consumers must use ``EventSource(url, { withCredentials: true })``. */
  streamUrl: () =>
    `${API_BASE_URL}/notifications/stream`,
}

// ── Social Posts API ──────────────────────────────────────────────

export type SocialPostRow = {
  id: string
  review_id?: string
  post_code: string
  platform: string
  content_type: string
  preview: string | null
  full_content: string
  url: string | null
  created_at: string
  compliance_status: "pass" | "fail" | "conditional" | "pending"
  total_flags: number
}

export const socialPostsApi = {
  list: (orgSlug: string) => apiRequest<SocialPostRow[]>(`${tenantApiPrefix(orgSlug)}/social-posts`),
  get: (orgSlug: string, id: string) =>
    apiRequest<SocialPostRow>(`${tenantApiPrefix(orgSlug)}/social-posts/${id}`),
  getReviewByPostId: (orgSlug: string, postId: string) =>
    apiRequest<any>(`${tenantApiPrefix(orgSlug)}/social-posts/${postId}/review`),
}

// ── Monitoring API ────────────────────────────────────────────────

export type MonitoredProfile = {
  id: string
  url: string
  display_name: string
  status: "active" | "paused"
  check_frequency: "daily"
  check_time: string | null
  last_checked_at: string | null
  posts_reviewed: number
  flagged_posts: number
  added_by: string
  created_at: string
  updated_at: string
}

export type MonitoringRunResult = {
  ok: boolean
  run_at: string
  profiles_checked: number
  processed: number
  skipped: number
  errors: number
  profile_results: Array<{
    monitor_id: string
    url: string
    display_name: string
    status: "processed" | "skipped" | "skipped_existing" | "no_posts" | "error"
    latest_post_id?: string
    review_id?: string
    violations_count?: number
    message: string
  }>
}

export type EmailDigestRecipient = { id: string; email: string }
export type EmailDigestSettings = {
  digest_time: string | null
  enabled: boolean
  recipients: EmailDigestRecipient[]
}

export const monitoringApi = {
  listProfiles: (orgSlug: string) =>
    apiRequest<MonitoredProfile[]>(`${tenantApiPrefix(orgSlug)}/monitoring/profiles`),

  createProfile: (
    orgSlug: string,
    payload: { url: string; display_name: string; status?: string; check_frequency?: string; check_time?: string }
  ) =>
    apiRequest<MonitoredProfile>(`${tenantApiPrefix(orgSlug)}/monitoring/profiles`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateProfile: (orgSlug: string, id: string, payload: { status?: string; check_frequency?: string; check_time?: string }) =>
    apiRequest<MonitoredProfile>(`${tenantApiPrefix(orgSlug)}/monitoring/profiles/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  deleteProfile: (orgSlug: string, id: string) =>
    apiRequest<{ ok: boolean }>(`${tenantApiPrefix(orgSlug)}/monitoring/profiles/${id}`, { method: "DELETE" }),

  runNow: (orgSlug: string) =>
    apiRequest<MonitoringRunResult>(`${tenantApiPrefix(orgSlug)}/social-posts/monitor/run`, { method: "POST" }),

  runProfile: (orgSlug: string, profileId: string) =>
    apiRequest<MonitoringRunResult["profile_results"][0] & { ok: boolean; run_at: string }>(
      `${tenantApiPrefix(orgSlug)}/social-posts/monitor/run/${profileId}`,
      { method: "POST" }
    ),

  getDigestSettings: (orgSlug: string) =>
    apiRequest<EmailDigestSettings>(`${tenantApiPrefix(orgSlug)}/monitoring/digest-settings`),

  updateDigestSettings: (orgSlug: string, payload: { enabled: boolean; recipients: string[] }) =>
    apiRequest<any>(`${tenantApiPrefix(orgSlug)}/monitoring/digest-settings`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
}

// ── Reports API ────────────────────────────────────────────────

export type ComplianceReportRow = {
  id: string
  report_code: string
  review_id: string
  review_type: string
  compliance_status: string
  total_flags: number
  high_risk_flags: number
  medium_risk_flags: number
  low_risk_flags: number
  approval_authority: string
  approval_role: string
  approval_timestamp: string
  ai_summary?: string
  created_at: string
  document_name?: string
  approval_authority_name?: string
  /** From document_versions (marketing docs); absent for some social reviews */
  version_label?: string | null
}

export const reportsApi = {
  list: (orgSlug: string) =>
    apiRequest<ComplianceReportRow[]>(`${tenantApiPrefix(orgSlug)}/compliance-reports`),
  getById: (orgSlug: string, id: string) =>
    apiRequest<ComplianceReportRow>(`${tenantApiPrefix(orgSlug)}/compliance-reports/${id}`),
  getDownloadPdfUrl: (orgSlug: string, id: string) => {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
    return `${API_BASE_URL}${tenantApiPrefix(orgSlug)}/compliance-reports/${id}/pdf?timezone=${encodeURIComponent(tz)}`
  },
  getPdfBlob: async (orgSlug: string, id: string) => {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
    const response = await fetch(`${API_BASE_URL}${tenantApiPrefix(orgSlug)}/compliance-reports/${id}/pdf?timezone=${encodeURIComponent(tz)}`, {
      credentials: "include"
    })
    if (!response.ok) throw new Error("Failed to load PDF")
    return await response.blob()
  }
}