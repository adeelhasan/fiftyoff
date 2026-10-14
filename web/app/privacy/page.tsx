import type { Metadata } from "next";
import { Legal } from "@/components/Legal";

export const metadata: Metadata = { title: "Privacy" };

// Placeholder: the policy itself must come from counsel (design/README.md, "Accounts, plan and legal").
export default function Page() {
  return (
    <Legal
      title="Privacy"
      updated="13 OCT 2026"
      short={<p>You don&apos;t need an account to browse. We set no cookies of our own, and clicks are logged without your IP address. Alerts aren&apos;t live yet, so we don&apos;t collect email addresses.</p>}
      sections={[
        {
          id: "browse",
          title: "Browsing",
          body: (
            <p>
              Your browser keeps two values on your device: when you last looked, so we can show what&apos;s new since then, and
              which of two versions of the home page you see (a letter, a or b), so we can tell which one works better. Only
              that letter ever leaves your device. We count page views per day and page, with that letter and nothing else:
              no IP address, no cookie, no id.
            </p>
          ),
        },
        {
          id: "clicks",
          title: "Clicks to Amazon",
          body: <p>When you open a deal, we record which deal it was, the time, the fiftyOff page and spot you came from, and the a/b letter above. Not who you are, and not your IP address.</p>,
        },
        {
          id: "email",
          title: "Email",
          body: <p>&ldquo;Watch this shelf&rdquo; doesn&apos;t send or store your address yet. When alerts start, this page will say what we keep and how to delete it.</p>,
        },
        {
          id: "others",
          title: "Others involved",
          body: <p>Pages are delivered through Cloudflare. Product photos load from Amazon&apos;s image servers. Prices come from Keepa.</p>,
        },
      ]}
    />
  );
}
