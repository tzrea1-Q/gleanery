import { createFileRoute } from "@tanstack/react-router";
import { PlatformAccounts } from "@/components/platform/PlatformAccounts";

export const Route = createFileRoute("/accounts")({ component: PlatformAccounts });
