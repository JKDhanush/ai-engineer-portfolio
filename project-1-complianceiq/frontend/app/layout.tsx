import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "ComplianceIQ — RBI KYC/AML copilot",
  description: "Grounded answers about RBI KYC / AML rules with circular- and paragraph-level citations.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <Nav />
        {children}
      </body>
    </html>
  );
}
