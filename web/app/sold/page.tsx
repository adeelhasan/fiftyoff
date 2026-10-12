import type { Metadata } from "next";
import Sold from "@/components/pages/Sold";

// /d/{slug} sends a click here (/sold/?id={asin}) when the unit is no longer live.
export const metadata: Metadata = { title: "Gone" };

export default function Page() {
  return <Sold />;
}
