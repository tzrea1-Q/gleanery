import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { settleConfirm, useConfirmStore } from "@/stores/confirm";

export function ConfirmHost() {
  const request = useConfirmStore((s) => s.request);
  return (
    <AlertDialog
      open={request !== null}
      onOpenChange={(open) => {
        if (!open) settleConfirm(false);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{request?.title}</AlertDialogTitle>
          {/* 没有说明时也要渲染，否则 Radix 会警告弹窗缺少描述 */}
          <AlertDialogDescription>{request?.description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction
            variant={request?.destructive ? "destructive" : "default"}
            onClick={() => settleConfirm(true)}
          >
            {request?.confirmLabel ?? "确定"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
