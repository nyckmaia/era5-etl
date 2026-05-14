import {
  Outlet,
  createRootRouteWithContext,
  createRoute,
  redirect,
} from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";

import { Layout } from "./components/Layout";
import { DashboardPage } from "./pages/Dashboard";
import { DownloadWizardPage } from "./pages/DownloadWizard";
import { InventoryPage } from "./pages/Inventory";
import { QueryPage } from "./pages/Query";
import { SettingsPage } from "./pages/Settings";

interface RouterContext {
  queryClient: QueryClient;
}

export const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: () => (
    <Layout>
      <Outlet />
    </Layout>
  ),
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: () => {
    throw redirect({ to: "/dashboard" });
  },
});

const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/dashboard",
  component: DashboardPage,
});

const inventoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/inventory",
  component: InventoryPage,
});

const downloadRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/download",
  component: DownloadWizardPage,
});

const queryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/query",
  component: QueryPage,
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: SettingsPage,
});

export const routeTree = rootRoute.addChildren([
  indexRoute,
  dashboardRoute,
  inventoryRoute,
  downloadRoute,
  queryRoute,
  settingsRoute,
]);
