import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { UserProvider } from "@/lib/UserContext";

export const metadata: Metadata = {
  title: "СтройКонтроль",
  description: "Система управления строительными проектами",
};

export default function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <html lang="ru">
      <body>
        <UserProvider>{children}</UserProvider>
      </body>
    </html>
  );
}
