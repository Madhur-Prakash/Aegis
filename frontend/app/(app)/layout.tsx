/**
 * Everything behind the shell.  A route group, so the URLs stay `/deals`,
 * `/review`, `/settings` -- the nav is a layout concern, not a path segment.
 */

import { Shell } from "@/components/domain/Shell";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <Shell>{children}</Shell>;
}
