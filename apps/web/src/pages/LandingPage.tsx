import { Show, SignInButton, UserButton } from "@clerk/react";
import { Code2 } from "lucide-react";
import { Link } from "react-router-dom";

import { buttonVariants } from "../components/ui/button";
import { cn } from "../lib/utils";

const clerkEnabled = !!import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

export function LandingPage() {
  return (
    <div className="landing-root">
      <header className="landing-header">
        <div className="landing-brand">
          <span className="landing-logo">
            <Code2 aria-hidden />
          </span>
          <span className="landing-brand-text">Dynamic Agent Studio</span>
        </div>
        <nav className="landing-nav">
          {clerkEnabled ? (
            <>
              <Show when="signed-out">
                <div className="landing-clerk-actions">
                  <SignInButton />
                </div>
              </Show>
              <Show when="signed-in">
                <UserButton />
              </Show>
            </>
          ) : null}
          <Link to="/workbench" className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
            Open workbench
          </Link>
        </nav>
      </header>

      <main className="landing-main">
        <p className="landing-kicker">Professional web IDE</p>
        <h1 className="landing-title">Dynamic agent creation</h1>
        <p className="landing-lead">
          Build and run coding agents in isolated workspaces. Edit files, stream reasoning, and ship changes—all in one calm,
          keyboard-first surface.
        </p>
        <div className="landing-actions">
          <Link to="/workbench" className={cn(buttonVariants({ size: "lg" }), "landing-primary-link")}>
            Open workbench
          </Link>
        </div>
      </main>
    </div>
  );
}
