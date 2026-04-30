import { ClerkProvider } from "@clerk/react";
import { StrictMode } from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY ?? "";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    {/* Key must be set in `.env.local` as VITE_CLERK_PUBLISHABLE_KEY — see https://clerk.com/docs/react/getting-started/quickstart */}
    <ClerkProvider publishableKey={publishableKey} afterSignOutUrl="/">
      <App />
    </ClerkProvider>
  </StrictMode>,
);
