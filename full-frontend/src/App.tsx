import { Navigate, Outlet, Route, Routes } from "react-router-dom"

import { RequireAppAccessLayout } from "@/components/auth/RequireAppAccessLayout"
import { AppShell } from "@/components/layout/AppShell"
import {
  LegacyAuditTrailRedirect,
  LegacyDashboardDefaultRedirect,
  LegacyPublishedDocumentsRedirect,
  LegacyReportDetailRedirect,
  LegacyReportsRedirect,
  LegacyUploadDocumentRedirect,
  LegacyValidateDocumentDetailRedirect,
  LegacyValidateDocumentsRedirect,
} from "@/components/routing/LegacyOrgRedirects"
import DashboardPage from "./pages/dashboard"
import LoginPage from "./pages/login"
import LoginOtpPage from "./pages/loginotp"
import ForgotPasswordPage from "./pages/forgotpassword"
import ComingSoonPage from "./pages/comingsoon"
import ValidateDocumentsPage from "./pages/validatedocuments"
import DocumentDetailPage from "./pages/documentdetail"
import RegisterPage from "./pages/register"
import RegisterOtpPage from "./pages/registerotp"
import PublishedDocumentsPage from "./pages/publisheddocuments"
import ReportsPage from "./pages/reports"
import ReportDetailPage from "./pages/reportdetail"
import UploadDocumentPage from "./pages/uploaddocument"
import AuditTrailPage from "./pages/audittrail"

import SuperAdminPage from "./pages/superAdmin"
import UserProfilePage from "./pages/userProfile"
import AssignRolePage from "./pages/assignRole"
import PendingAccessPage from "./pages/pendingAccess"
import OwnerMultitenancyPage from "./pages/ownerMultitenancy"
import OwnerOrganizationsPage from "./pages/ownerOrganizations"

export default function App() {
  return (
    <Routes>
      {/* Default route */}
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/loginotp" element={<LoginOtpPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/register" element={<Navigate to="/login" replace />} />
      <Route path="/registerotp" element={<Navigate to="/login" replace />} />

      {/*
        AppShell is mounted ONCE as a shared layout so the sidebar does not
        re-mount on every navigation. All routes that render <MainLayout/>
        must be nested inside this block.
      */}
      <Route element={<AppShell />}>
        <Route path="/user-profile" element={<UserProfilePage />} />

        <Route element={<RequireAppAccessLayout />}>
          <Route path="/pending-access" element={<PendingAccessPage />} />
          <Route path="/dashboard" element={<LegacyDashboardDefaultRedirect />} />
          <Route path="/dashboard/default" element={<LegacyDashboardDefaultRedirect />} />
          <Route path="/dashboard/overview" element={<LegacyDashboardDefaultRedirect />} />
          <Route path="/activities" element={<ComingSoonPage />} />
          <Route path="/validate-documents" element={<LegacyValidateDocumentsRedirect />} />
          <Route path="/validate-documents/detail/:docId" element={<LegacyValidateDocumentDetailRedirect />} />
          <Route path="/upload-document" element={<LegacyUploadDocumentRedirect />} />
          <Route path="/published-documents" element={<LegacyPublishedDocumentsRedirect />} />
          <Route path="/reports" element={<LegacyReportsRedirect />} />
          <Route path="/reports/:id" element={<LegacyReportDetailRedirect />} />
          <Route path="/audit-trail" element={<LegacyAuditTrailRedirect />} />
          <Route path="/super-admin" element={<SuperAdminPage />} />
          <Route path="/user-roles" element={<AssignRolePage />} />
          <Route path="/owner/multitenancy" element={<OwnerMultitenancyPage />} />
          <Route path="/owner/organizations" element={<OwnerOrganizationsPage />} />

          <Route path="/orgs/:orgSlug" element={<Outlet />}>
            <Route path="dashboard" element={<Navigate to="default" replace />} />
            <Route path="dashboard/default" element={<DashboardPage />} />
            <Route path="dashboard/overview" element={<DashboardPage />} />
            <Route path="activities" element={<ComingSoonPage />} />
            <Route path="validate-documents" element={<ValidateDocumentsPage />} />
            <Route path="validate-documents/detail/:docId" element={<DocumentDetailPage />} />
            <Route path="upload-document" element={<UploadDocumentPage />} />
            <Route path="published-documents" element={<PublishedDocumentsPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="reports/:id" element={<ReportDetailPage />} />
            <Route path="audit-trail" element={<AuditTrailPage />} />
          </Route>
        </Route>
      </Route>

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
