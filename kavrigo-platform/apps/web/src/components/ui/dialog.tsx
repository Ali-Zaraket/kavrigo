"use client";
// Adapted from shadcn/ui base-nova/dialog (MIT), using Base UI focus management.
import { Dialog as Primitive } from "@base-ui/react/dialog";
export const Dialog = Primitive.Root;
export const DialogTrigger = Primitive.Trigger;
export const DialogClose = Primitive.Close;
export const DialogTitle = Primitive.Title;
export const DialogDescription = Primitive.Description;
export function DialogContent({ children }: { children: React.ReactNode }) {
  return (
    <Primitive.Portal>
      <Primitive.Backdrop className="dialog-backdrop" />
      <Primitive.Popup
        className="dialog-content"
        finalFocus={() => document.getElementById("main")}
      >
        {children}
        <Primitive.Close className="dialog-close" aria-label="Close dialog">
          ×
        </Primitive.Close>
      </Primitive.Popup>
    </Primitive.Portal>
  );
}
