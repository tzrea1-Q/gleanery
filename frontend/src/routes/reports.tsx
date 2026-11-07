import { createFileRoute } from "@tanstack/react-router";
import { ReportList } from "@/components/report/ReportList";

export const Route = createFileRoute("/reports")({ component: ReportList });
