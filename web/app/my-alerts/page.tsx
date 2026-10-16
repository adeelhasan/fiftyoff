import type { Metadata } from "next";
import MyAlerts from "@/components/pages/MyAlerts";

export const metadata: Metadata = { title: "My alerts" };

export default function Page() {
  return <MyAlerts />;
}
