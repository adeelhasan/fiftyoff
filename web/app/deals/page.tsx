import type { Metadata } from "next";
import AllDeals from "@/components/pages/AllDeals";

export const metadata: Metadata = { title: "All deals" };

export default function Page() {
  return <AllDeals />;
}
