import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Orin Control Center",
  description: "A local view of your Orin agent runtime.",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
};

const themeBootstrap = `var saved=null;try{saved=localStorage.getItem("orin-theme")}catch{}document.documentElement.dataset.theme=saved==="light"||saved==="dark"?saved:matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrap }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
