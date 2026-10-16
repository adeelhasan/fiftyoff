import type { Metadata, Viewport } from "next";
import { Footer, Header } from "@/components/Chrome";
import { DealSheet } from "@/components/DealSheet";
import { AlertProvider } from "@/components/Alert";
import { display, grade, mono, text } from "./fonts";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "fiftyOff", template: "%s · fiftyOff" },
  description: "Open-box and used products from Amazon Resale, at about half their usual price.",
  robots: { index: false, follow: false },
  icons: { icon: "/icon.svg" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#FFFFFF" },
    { media: "(prefers-color-scheme: dark)", color: "#2C2D29" },
  ],
};

// tokens.css keys dark mode off [data-theme="dark"]: set it from the system setting before first paint.
// localStorage "fo:theme" (light|dark) overrides it, for review now and a toggle later.
const THEME = `(function(){var m=matchMedia('(prefers-color-scheme: dark)'),o;try{o=localStorage.getItem('fo:theme')}catch(e){}function s(){document.documentElement.dataset.theme=o==='light'||o==='dark'?o:m.matches?'dark':'light'}s();m.addEventListener('change',s)})()`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${display.variable} ${text.variable} ${mono.variable} ${grade.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME }} />
        <link rel="preconnect" href="https://m.media-amazon.com" />
      </head>
      <body>
        <AlertProvider>
          <div className="shell">
            <a className="skip" href="#main">
              Skip to deals
            </a>
            <Header />
            <main className="wrap" id="main" tabIndex={-1}>
              {children}
            </main>
            <Footer />
          </div>
          <DealSheet />
        </AlertProvider>
      </body>
    </html>
  );
}
