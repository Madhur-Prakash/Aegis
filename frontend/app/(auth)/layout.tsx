/**
 * The auth screens get no nav: there is nothing to navigate to yet, and a nav
 * full of links that all 401 is worse than no nav at all.
 */

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <div className="auth-screen">{children}</div>;
}
