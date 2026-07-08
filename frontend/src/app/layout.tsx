import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI Executive Assistant",
  description: "Kişisel yapay zekâ yönetici asistanı",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="tr">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif" }}>
        {children}
      </body>
    </html>
  );
}
