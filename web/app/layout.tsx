import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Orin Control Center",
  description: "A local view of your Orin agent runtime.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
