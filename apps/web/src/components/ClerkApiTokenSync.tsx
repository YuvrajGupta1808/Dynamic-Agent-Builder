import { useAuth } from "@clerk/react";
import { useEffect } from "react";

import { setClerkTokenGetter } from "../lib/auth-token";

/** Registers Clerk session JWT for `resolveApiToken`; render only when `<Show when="signed-in">` wraps the workbench. */
export function ClerkApiTokenSync() {
  const { getToken, isSignedIn } = useAuth();

  useEffect(() => {
    if (!isSignedIn) {
      setClerkTokenGetter(null);
      return;
    }
    setClerkTokenGetter(() => getToken());
    return () => setClerkTokenGetter(null);
  }, [getToken, isSignedIn]);

  return null;
}
