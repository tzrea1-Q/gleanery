import { useAcknowledgeDisclaimer, useAppState } from "@/api/queries";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Notice } from "@/components/common/Notice";
import { Button } from "@/components/ui/button";

export function DisclaimerDialog() {
  const state = useAppState();
  const ack = useAcknowledgeDisclaimer();
  return (
    <Dialog open={state.data?.disclaimer_acknowledged === false}>
      <DialogContent
        showCloseButton={false}
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
      >
        <DialogTitle>使用声明</DialogTitle>
        <DialogDescription>请在使用前了解以下事项。</DialogDescription>
        <ul className="list-disc space-y-2 pl-5">
          <li>只采集账号本来就能看到的公开内容，用于个人研究。</li>
          <li>请遵守平台协议。</li>
          <li>默认保守限速，遇到风控即停止。</li>
          <li>本项目不提供签名算法、代理池、多账号，也不提供绕过验证码的能力。</li>
        </ul>
        <Button disabled={ack.isPending} onClick={() => ack.mutate()}>
          我知道了
        </Button>
        {ack.isError && <Notice>保存失败，请重试</Notice>}
      </DialogContent>
    </Dialog>
  );
}
