import { createFileRoute } from "@tanstack/react-router";
import { ConversationThread } from "@/components/chat/ConversationThread";

export const Route = createFileRoute("/c/$conversationId")({ component: Conversation });
function Conversation() {
  const { conversationId } = Route.useParams();
  return <ConversationThread id={conversationId} />;
}
