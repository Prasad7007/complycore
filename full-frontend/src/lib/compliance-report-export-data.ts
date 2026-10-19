import { auditApi, findingsApi } from "@/lib/api"
import type { AuditTrailEvent, ComplianceFinding } from "@/lib/report-export"

export async function loadComplianceReportExportPayload(
  orgSlug: string,
  reviewId: string | null | undefined
): Promise<{ findings: ComplianceFinding[]; auditEvents: AuditTrailEvent[] }> {
  if (!reviewId) {
    return { findings: [], auditEvents: [] }
  }
  const [findings, auditRes] = await Promise.all([
    findingsApi.getFindings(orgSlug, reviewId).catch(() => []),
    auditApi.getUnifiedAuditTrail(orgSlug, reviewId).catch(() => ({ events: [] as AuditTrailEvent[] })),
  ])
  return {
    findings: findings as ComplianceFinding[],
    auditEvents: auditRes?.events ?? [],
  }
}
