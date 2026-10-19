from fastapi import APIRouter
from apis.v1.routers import auth, users, rbac, documents, compliance_rules, \
    reviews, workflows, findings, content_comments_reports, \
    audit, notifications, organizations, org_invites, health
api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(rbac.router)
api_router.include_router(health.router)
tenant_router = APIRouter(prefix="/orgs/{org_slug}")
tenant_router.include_router(documents.router)
tenant_router.include_router(findings.router)
tenant_router.include_router(findings.reviews_feedback_router)
tenant_router.include_router(org_invites.router)
tenant_router.include_router(reviews.router)
tenant_router.include_router(workflows.router)
tenant_router.include_router(content_comments_reports.router)
tenant_router.include_router(content_comments_reports.reports_router)
tenant_router.include_router(audit.router)
tenant_router.include_router(audit.global_audit_router)
api_router.include_router(tenant_router)

api_router.include_router(org_invites.accept_router)

api_router.include_router(compliance_rules.router)
api_router.include_router(notifications.router)
api_router.include_router(organizations.router)