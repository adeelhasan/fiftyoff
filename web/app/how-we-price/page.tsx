import type { Metadata } from "next";
import { Legal } from "@/components/Legal";

export const metadata: Metadata = { title: "How we price" };

export default function Page() {
  return (
    <Legal
      title="How we price"
      updated="11 OCT 2026"
      short={<p>We list an Amazon Resale unit when its price is about half of what the product usually sells for, or less. The usual price comes from the product&apos;s real price history, not from a list price.</p>}
      sections={[
        {
          id: "usual",
          title: "The usual price",
          body: (
            <p>
              We take the lower of Amazon&apos;s own price and the lowest new price from other sellers, now and on average over
              recent months, using <a href="https://keepa.com" rel="noopener">Data by Keepa</a>. When they disagree, the lowest
              one wins, so the discount is never flattered. An inflated &ldquo;list price&rdquo; never counts.
            </p>
          ),
        },
        {
          id: "off",
          title: "The % off",
          body: <p>The stamp on each card compares the Resale unit&apos;s price with that usual price. We only show units at 50% off or more, on products that usually sell for $40 or more.</p>,
        },
        {
          id: "checks",
          title: "Checks",
          body: <p>We check listed units again during the day. When a unit hasn&apos;t been seen for 6 hours we call it gone: usually it sold, sometimes it was withdrawn.</p>,
        },
        {
          id: "links",
          title: "Links",
          body: <p>Every card links through fiftyOff to the product on Amazon, so we can count clicks and send you to a &ldquo;gone&rdquo; page if the unit has already sold. There are no affiliate links.</p>,
        },
      ]}
    />
  );
}
