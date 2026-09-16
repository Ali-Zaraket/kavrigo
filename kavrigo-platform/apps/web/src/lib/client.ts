import createClient from "openapi-fetch";
import type { paths, components } from "./schema";

export type Schema = components["schemas"];
export const apiClient = (token: string) =>
  createClient<paths>({
    baseUrl: "/api/control",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
export function unwrap<T>(result: {
  data?: T;
  error?: unknown;
  response: Response;
}): T {
  if (!result.response.ok || result.data === undefined) {
    const error = result.error as
      { message?: string; code?: string; request_id?: string } | undefined;
    throw new Error(
      `${error?.message ?? "Request failed."}${error?.request_id ? ` Reference: ${error.request_id}` : ""}`,
    );
  }
  return result.data;
}
/** Exact string formatting: never convert money/quantity to IEEE-754 numbers. */
export function decimal(value: string): string {
  if (!/^-?\d+(\.\d+)?$/.test(value)) return value;
  const [whole, fraction] = value.split(".");
  return (
    whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") +
    (fraction ? `.${fraction}` : "")
  );
}
export const money = (value: { amount: string; currency: string }) =>
  `${decimal(value.amount)} ${value.currency}`;
export const utc = (value: string) =>
  value.replace("T", " ").replace(/(\.\d+)?(Z|\+00:00)$/, " UTC");
