import type { Metadata } from "next";
import { Legal } from "@/components/Legal";

export const metadata: Metadata = { title: "Privacy" };

// Placeholder: the policy itself must come from counsel (design/README.md, "Accounts, plan and legal").
export default function Page() {
  return (
    <Legal
      title="Privacy"
      updated="15 OCT 2026"
      short={<p>You don&apos;t need an account to browse. We set no cookies of our own unless you set an alert, and clicks are logged without your IP address. If you set an alert, we keep your email address and your keywords, only to send your alerts.</p>}
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
          body: (
            <p>
              If you set an alert, we keep your email address, the keywords you watch, where on the site you set each one
              (a search, a deal page, a gone deal), when it started and ended, and which deals we emailed you or missed. We use
              them only to send your alerts and sign-in links; the emails go out through Resend. Confirming an alert signs you
              in on that browser with one cookie (90 days, nothing else in it). Stop or pause alerts from any email or from My
              alerts. To have your address and alerts deleted, ask through the Contact page; a delete button is coming.
            </p>
          ),
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
