import type { Metadata } from "next";
import { Legal } from "@/components/Legal";

export const metadata: Metadata = { title: "How we price" };

export default function Page() {
  return (
    <Legal
      title="How we price"
      updated="13 OCT 2026"
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
          body: (
            <p>
              Some units we check again ourselves during the day; when one hasn&apos;t been seen for 6 hours we call it gone:
              usually it sold, sometimes it was withdrawn. Most others we know from Keepa&apos;s deal feed, and we drop them when
              the feed hasn&apos;t shown them for a day and a half. Each card says how long ago it was last seen.
            </p>
          ),
        },
        {
          id: "conditions",
          title: "Conditions and returns",
          body: (
            <>
              <p>
                Every unit is an Amazon Resale item: a return or open-box product that Amazon has inspected and graded. In
                short, following Amazon&apos;s condition guidelines:
              </p>
              <ul>
                <li><b>Like New:</b> works perfectly and looks unused. The box may be damaged or replaced.</li>
                <li><b>Very Good:</b> works perfectly, with little sign of use. It may be missing its box or minor extras.</li>
                <li><b>Good:</b> works perfectly, with visible signs of use such as scuffs or scratches. It may be missing its box or extras.</li>
                <li><b>Acceptable:</b> works, with clear wear, and may lack its box or extras. We hide these unless you ask for them.</li>
              </ul>
              <p>
                Units are sold and shipped by Amazon, with Amazon&apos;s normal returns. The listing on Amazon shows the exact grade
                notes for that unit; check them before you buy. Jewelry and watches are graded the same way: a Like New watch
                may have been tried on and returned.
              </p>
            </>
          ),
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
