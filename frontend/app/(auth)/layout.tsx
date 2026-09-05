/**
 * The auth screens get no nav: there is nothing to navigate to yet, and a nav
 * full of links that all 401 is worse than no nav at all.
 *
 * Behind the card, the same generated hairline lattice the hero uses, at 4%
 * (ui/06 §7). It is the one thing that makes a centred 380px column read as
 * part of this product rather than as a default form page -- and it is
 * generated, because Aegis has no lifestyle imagery to put there.
 */

import { Lattice } from "@/components/ui/Reveal";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="auth-screen">
      <Lattice opacity={0.04} />
      {children}
    </div>
  );
}
