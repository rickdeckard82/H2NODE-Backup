import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";
import { Spinner, ToastProvider } from "./components/ui";
import { AppShell } from "./layouts/AppShell";
import { useAuth, type Role } from "./lib/auth";

const LoginPage = lazy(() => import("./features/auth/LoginPage"));
const DashboardPage = lazy(() => import("./features/dashboard/DashboardPage"));
const ClientsPage = lazy(() => import("./features/clients/ClientsPage"));
const DevicesPage = lazy(() => import("./features/devices/DevicesPage"));
const FtpAccountsPage = lazy(() => import("./features/settings/FtpAccountsPage"));
const AccountsPage = lazy(() => import("./features/accounts/AccountsPage"));
const BackupsPage = lazy(() => import("./features/backups/BackupsPage"));
const ServerPage = lazy(() => import("./features/settings/ServerPage"));
const SystemUsersPage = lazy(() => import("./features/system-users/SystemUsersPage"));
const AuditPage = lazy(() => import("./features/audit/AuditPage"));
const DecryptHelpPage = lazy(() => import("./features/help/DecryptHelpPage"));
const CpanelHelpPage = lazy(() => import("./features/help/CpanelHelpPage"));
const Unm2000HelpPage = lazy(() => import("./features/help/Unm2000HelpPage"));
const LinuxHelpPage = lazy(() => import("./features/help/LinuxHelpPage"));
const DatacomHelpPage = lazy(() => import("./features/help/DatacomHelpPage"));
const JuniperHelpPage = lazy(() => import("./features/help/JuniperHelpPage"));

function Loader() {
  return (
    <div className="flex h-screen items-center justify-center text-brand-600">
      <Spinner className="h-8 w-8" />
    </div>
  );
}

function Protected({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user, loading, can } = useAuth();
  if (loading) return <Loader />;
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !can(...roles)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function Shell() {
  return (
    <ToastProvider>
      <Protected>
        <AppShell>
          <Suspense fallback={<Loader />}>
            <Outlet />
          </Suspense>
        </AppShell>
      </Protected>
    </ToastProvider>
  );
}

export const router = createBrowserRouter([
  {
    path: "/login",
    element: (
      <Suspense fallback={<Loader />}>
        <LoginPage />
      </Suspense>
    ),
  },
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "clients", element: <ClientsPage /> },
      { path: "devices", element: <DevicesPage /> },
      { path: "backups", element: <BackupsPage /> },
      { path: "accounts", element: <AccountsPage /> },
      {
        path: "settings/ftp-accounts",
        element: (
          <Protected roles={["admin"]}>
            <FtpAccountsPage />
          </Protected>
        ),
      },
      { path: "settings/server", element: <ServerPage /> },
      {
        path: "system-users",
        element: (
          <Protected roles={["admin"]}>
            <SystemUsersPage />
          </Protected>
        ),
      },
      {
        path: "audit",
        element: (
          <Protected roles={["admin"]}>
            <AuditPage />
          </Protected>
        ),
      },
      { path: "help/decrypt", element: <DecryptHelpPage /> },
      { path: "help/linux", element: <LinuxHelpPage /> },
      { path: "help/cpanel", element: <CpanelHelpPage /> },
      { path: "help/unm2000", element: <Unm2000HelpPage /> },
      { path: "help/juniper", element: <JuniperHelpPage /> },
      { path: "help/datacom", element: <DatacomHelpPage /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
