import type { Metadata } from "next";
import { Legal } from "@/components/Legal";

export const metadata: Metadata = { title: "Contact" };

// Placeholder: a contact address comes with alerts and accounts.
export default function Page() {
  return (
    <Legal
      title="Contact"
      updated="11 OCT 2026"
      short={<p>fiftyOff is a small, independent site. We aren&apos;t Amazon and can&apos;t help with orders, returns or refunds.</p>}
      sections={[
        {
          id: "orders",
          title: "Orders and returns",
          body: <p>Units are sold and shipped by Amazon under its normal return rules. Contact Amazon about anything you bought.</p>,
        },
        {
          id: "us",
          title: "Reaching us",
          body: <p>A contact address is coming with email alerts. Until then this page is a placeholder.</p>,
        },
      ]}
    />
  );
}
