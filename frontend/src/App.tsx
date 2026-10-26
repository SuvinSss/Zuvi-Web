import { Navigate, NavLink, Outlet, Route, Routes, useParams } from "react-router-dom";
import { DeliverToButton } from "./components/location/DeliverToButton";
import { LocationDialog } from "./components/location/LocationDialog";
import { Alert, Button, Loading } from "./components/ui";
import type { Portal } from "./lib/types";
import { AdminAssignments } from "./pages/admin/AdminAssignments";
import { AdminMaps } from "./pages/admin/AdminMaps";
import { AdminPricing } from "./pages/admin/AdminPricing";
import { AdminStores } from "./pages/admin/AdminStores";
import { Addresses } from "./pages/customer/Addresses";
import { Checkout } from "./pages/customer/Checkout";
import { NearbyStores } from "./pages/customer/NearbyStores";
import { OrderTracking } from "./pages/customer/OrderTracking";
import { Assignments } from "./pages/delivery/Assignments";
import { Login } from "./pages/Login";
import { StoreLocationPage } from "./pages/store/StoreLocationPage";
import { StoreOrdersPage } from "./pages/store/StoreOrdersPage";
import { useSession } from "./state/session";

const NAV: Record<Portal, { to: string; label: string }[]> = {
  customer: [
    { to: "/customer/stores", label: "Stores near me" },
    { to: "/customer/addresses", label: "Addresses" },
    { to: "/customer/checkout", label: "Checkout" },
  ],
  store: [
    { to: "/store/location", label: "Store location" },
    { to: "/store/orders", label: "Delivery orders" },
  ],
  delivery: [{ to: "/delivery", label: "My deliveries" }],
  admin: [
    { to: "/admin/maps", label: "Maps status" },
    { to: "/admin/stores", label: "Store locations" },
    { to: "/admin/pricing", label: "Delivery pricing" },
    { to: "/admin/assignments", label: "Assignments" },
  ],
};

const HOME: Record<Portal, string> = {
  customer: "/customer/stores",
  store: "/store/location",
  delivery: "/delivery",
  admin: "/admin/maps",
};

function Shell() {
  const { session, logout } = useSession();
  const portal = session?.portal;
  return (
    <>
      <header className="shell-header">
        <div className="inner">
          <a className="brand" href="/">ZuuVi</a>
          {portal === "customer" && <DeliverToButton />}
          {portal && (
            <nav className="nav" aria-label="Main">
              {NAV[portal].map((n) => (
                <NavLink key={n.to} to={n.to}>{n.label}</NavLink>
              ))}
              <Button variant="link" onClick={() => void logout()}>Sign out</Button>
            </nav>
          )}
        </div>
      </header>
      <main>
        <Outlet />
      </main>
      <LocationDialog />
    </>
  );
}

function RequirePortal({ portal }: { portal: Portal }) {
  const { session, loading, error, refresh } = useSession();
  if (loading) return <Loading label="Loading ZuuVi…" />;
  if (error)
    return (
      <Alert>
        {error} <Button variant="secondary" onClick={() => void refresh()}>Try again</Button>
      </Alert>
    );
  if (!session?.authenticated) return <Navigate to={`/login/${portal}`} replace />;
  if (session.portal !== portal) return <Navigate to={HOME[session.portal!]} replace />;
  return <Outlet />;
}

function Home() {
  const { session, loading } = useSession();
  if (loading) return <Loading />;
  if (session?.authenticated && session.portal) return <Navigate to={HOME[session.portal]} replace />;
  return (
    <div className="card">
      <h1>Welcome to ZuuVi</h1>
      <p className="muted">Choose how you'd like to sign in.</p>
      <div className="row">
        {(Object.keys(HOME) as Portal[]).map((p) => (
          <NavLink key={p} className="btn secondary" to={`/login/${p}`} style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}>
            {p === "delivery" ? "Delivery partner" : p[0]!.toUpperCase() + p.slice(1)}
          </NavLink>
        ))}
      </div>
    </div>
  );
}

function LoginRoute() {
  const { portal } = useParams();
  const valid = portal && portal in HOME;
  return valid ? <Login portal={portal as Portal} /> : <Navigate to="/" replace />;
}

export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Home />} />
        <Route path="login/:portal" element={<LoginRoute />} />
        <Route element={<RequirePortal portal="customer" />}>
          <Route path="customer/stores" element={<NearbyStores />} />
          <Route path="customer/addresses" element={<Addresses />} />
          <Route path="customer/checkout" element={<Checkout />} />
          <Route path="customer/orders/:orderNumber" element={<OrderTracking />} />
        </Route>
        <Route element={<RequirePortal portal="store" />}>
          <Route path="store/location" element={<StoreLocationPage />} />
          <Route path="store/orders" element={<StoreOrdersPage />} />
        </Route>
        <Route element={<RequirePortal portal="delivery" />}>
          <Route path="delivery" element={<Assignments />} />
        </Route>
        <Route element={<RequirePortal portal="admin" />}>
          <Route path="admin/maps" element={<AdminMaps />} />
          <Route path="admin/stores" element={<AdminStores />} />
          <Route path="admin/pricing" element={<AdminPricing />} />
          <Route path="admin/assignments" element={<AdminAssignments />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
