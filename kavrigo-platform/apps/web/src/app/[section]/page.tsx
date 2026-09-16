import { notFound } from "next/navigation";
import { Product } from "@/components/product";
const sections = [
  "studio",
  "research",
  "pulse",
  "portfolio",
  "risk",
  "paper",
  "integrations",
  "audit",
];
export default async function Page({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  if (!sections.includes(section)) notFound();
  return <Product section={section} />;
}
