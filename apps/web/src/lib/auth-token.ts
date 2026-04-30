const TOKEN_KEY = "agent-workbench-token";
const DEFAULT_TOKEN = import.meta.env.VITE_WORKBENCH_TOKEN ?? "dev-local-token";
let requireClerkJwt = false;

let clerkTokenGetter: (() => Promise<string | null>) | null = null;

export function setClerkTokenGetter(getter: (() => Promise<string | null>) | null) {
  clerkTokenGetter = getter;
}

export function setRequireClerkJwt(required: boolean) {
  requireClerkJwt = required;
}

export function isClerkJwtRequired() {
  return requireClerkJwt;
}

function legacyToken(): string {
  const existing = localStorage.getItem(TOKEN_KEY);
  if (existing) return existing;
  localStorage.setItem(TOKEN_KEY, DEFAULT_TOKEN);
  return DEFAULT_TOKEN;
}

/** Bearer token for API calls: Clerk JWT when signed in, else legacy dev token. */
export async function resolveApiToken(): Promise<string> {
  if (requireClerkJwt) {
    if (!clerkTokenGetter) {
      throw new Error("Sign in required");
    }
    try {
      const t = await clerkTokenGetter();
      if (t) return t;
    } catch {
      throw new Error("Sign in required");
    }
    throw new Error("Sign in required");
  }
  return legacyToken();
}

export function setLegacyWorkbenchToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function resetLegacyWorkbenchToken() {
  localStorage.setItem(TOKEN_KEY, DEFAULT_TOKEN);
  return DEFAULT_TOKEN;
}
