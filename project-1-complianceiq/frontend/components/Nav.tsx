"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, setToken, type User } from "@/lib/api";

export function Nav() {
  const path = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    api<User>("/auth/me").then(setUser).catch(() => setUser(null));
  }, [path]);

  const link = (href: string, label: string) => (
    <Link href={href} className={`px-3 py-1.5 rounded-md text-sm ${path === href
      ? "bg-white/15 text-white" : "text-white/70 hover:text-white"}`}>{label}</Link>
  );

  return (
    <header className="bg-ink text-white">
      <div className="mx-auto max-w-7xl px-4 h-14 flex items-center gap-6">
        <Link href="/" className="font-semibold tracking-tight">Compliance<span className="text-sky-300">IQ</span></Link>
        <nav className="flex gap-1">{link("/", "Ask")}{link("/admin", "Usage & cost")}</nav>
        <div className="ml-auto text-sm text-white/70 flex items-center gap-3">
          {user && user.email !== "anonymous" ? (
            <>
              <span>{user.email} · {user.role}</span>
              <button className="underline hover:text-white" onClick={() => { setToken(null); setUser(null);
                router.push("/login"); }}>Sign out</button>
            </>
          ) : (
            <Link href="/login" className="hover:text-white">Sign in</Link>
          )}
        </div>
      </div>
    </header>
  );
}
