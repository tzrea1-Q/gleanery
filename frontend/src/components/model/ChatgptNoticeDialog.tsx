import { useAcknowledgeChatgptNotice, useAppState, useModelConfigs } from "@/api/queries";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

export function ChatgptNoticeDialog() {
  const state = useAppState();
  const configs = useModelConfigs();
  const ack = useAcknowledgeChatgptNotice();
  const open =
    state.data?.disclaimer_acknowledged === true &&
    state.data.chatgpt_notice_acknowledged === false &&
    configs.data?.some((config) => config.kind === "chatgpt_plan" && config.status === "ok");
  return (
    <Dialog open={!!open}>
      <DialogContent
        showCloseButton={false}
        onInteractOutside={(event) => event.preventDefault()}
        onEscapeKeyDown={(event) => event.preventDefault()}
      >
        <DialogTitle>ChatGPT 套餐说明</DialogTitle>
        <DialogDescription>
          使用的是 ChatGPT 套餐额度，与 Codex 共享。Plus 有 5 小时窗口。
        </DialogDescription>
        <Button disabled={ack.isPending} onClick={() => ack.mutate()}>
          我知道了
        </Button>
        {ack.isError && <p role="alert">保存失败，请重试</p>}
      </DialogContent>
    </Dialog>
  );
}
