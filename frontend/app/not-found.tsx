/**
 * 404.
 *
 * Tenant isolation returns 404 rather than 403 for a resource that belongs to
 * someone else, so this page is also what a cross-tenant probe sees.  It
 * deliberately says nothing about whether the thing exists.
 */

import Link from "next/link";

export default function NotFound() {
  return (
    <div className="auth-screen">
      <div className="auth-card">
        <span className="mono-code">404</span>
        <h1 className="display-3">Not found</h1>
        <p className="state-body">
          There is nothing here that you can see. If you followed a link to a deal, it may belong to
          another organization.
        </p>
        <Link href="/" className="link">
          Home
        </Link>
      </div>
    </div>
  );
}
