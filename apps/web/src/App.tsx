import { ClerkLoaded, ClerkLoading, Show, SignIn, SignUp } from "@clerk/react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { ClerkApiTokenSync } from "./components/ClerkApiTokenSync";
import { LandingPage } from "./pages/LandingPage";
import { WorkbenchPage } from "./pages/WorkbenchPage";

const clerkEnabled = !!import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

function WorkbenchGate() {
  if (!clerkEnabled) {
    return <WorkbenchPage />;
  }
  return (
    <>
      <ClerkLoading>
        <div className="workbench-loading">
          <p>Loading session…</p>
        </div>
      </ClerkLoading>
      <ClerkLoaded>
        <Show when="signed-in" fallback={<Navigate to="/sign-in" replace />}>
          <ClerkApiTokenSync />
          <WorkbenchPage />
        </Show>
      </ClerkLoaded>
    </>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route
        path="/sign-in/*"
        element={clerkEnabled ? <SignIn routing="path" path="/sign-in" /> : <Navigate to="/" replace />}
      />
      <Route
        path="/sign-up/*"
        element={clerkEnabled ? <SignUp routing="path" path="/sign-up" /> : <Navigate to="/" replace />}
      />
      <Route path="/workbench" element={<WorkbenchGate />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
