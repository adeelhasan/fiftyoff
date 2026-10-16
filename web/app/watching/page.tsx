import type { Metadata } from "next";
import Watching from "@/components/pages/Watching";

export const metadata: Metadata = { title: "Watching" };

export default function Page() {
  return <Watching />;
}
