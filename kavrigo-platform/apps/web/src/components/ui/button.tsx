"use client";
// Adapted from shadcn/ui base-nova/button (MIT), registry inspected 2026-09-10.
// Kavrigo keeps a 44px target and avoids layout-shifting press animations.
import { Button as Primitive } from "@base-ui/react/button";
export function Button({
  className = "",
  variant = "default",
  ...props
}: Primitive.Props & { variant?: "default" | "outline" | "ghost" }) {
  return (
    <Primitive
      data-slot="button"
      className={`button button-${variant} ${className}`}
      {...props}
    />
  );
}
