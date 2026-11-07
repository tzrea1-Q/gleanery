import { createFileRoute } from "@tanstack/react-router";
import { DatasetList } from "@/components/dataset/DatasetList";

export const Route = createFileRoute("/datasets")({ component: DatasetList });
