import type { Metadata } from "next";
import RecentlyGone from "@/components/pages/RecentlyGone";

export const metadata: Metadata = { title: "Recently gone" };

export default function Page() {
  return <RecentlyGone />;
}
