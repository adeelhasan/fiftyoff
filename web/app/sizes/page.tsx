import type { Metadata } from "next";
import Sizes from "@/components/pages/Sizes";

export const metadata: Metadata = { title: "By size" };

export default function Page() {
  return <Sizes />;
}
