"use client";

import { createContext, useContext, useMemo, useState } from "react";
import { useAuth, useClerk } from "@clerk/nextjs";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { apiClient, unwrap } from "@/lib/client";

type Session = {
  token: string;
  hosted: boolean;
  signIn: (token: string) => void;
  signOut: () => void;
  workspace: string;
  setWorkspace: (id: string) => void;
  api: ReturnType<typeof apiClient>;
};
const Context = createContext<Session | null>(null);
export function useSession() {
  const session = useContext(Context);
  if (!session) throw new Error("Session missing");
  return session;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, staleTime: 0, refetchOnWindowFocus: true },
          mutations: { retry: false },
        },
      }),
  );
  const api = useMemo(() => apiClient(token), [token]);
  function reset(next: string) {
    void queryClient.cancelQueries();
    queryClient.clear();
    setWorkspace("");
    setToken(next);
  }
  return (
    <QueryClientProvider client={queryClient}>
      <Context.Provider
        value={{
          token,
          hosted: false,
          signIn: reset,
          signOut: () => reset(""),
          workspace,
          setWorkspace,
          api,
        }}
      >
        {children}
      </Context.Provider>
    </QueryClientProvider>
  );
}

/** Clerk owns the hosted session. A new user remounts this state and its query cache. */
export function HostedProviders({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn, userId, getToken } = useAuth();
  const clerk = useClerk();
  if (!isLoaded) return <p role="status">Checking your session…</p>;
  return (
    <HostedSession
      key={userId ?? "signed-out"}
      signedIn={!!isSignedIn}
      getToken={getToken}
      signOut={() => void clerk.signOut()}
    >
      {children}
    </HostedSession>
  );
}

function HostedSession({
  children,
  signedIn,
  getToken,
  signOut,
}: {
  children: React.ReactNode;
  signedIn: boolean;
  getToken: () => Promise<string | null>;
  signOut: () => void;
}) {
  const [workspace, setWorkspace] = useState("");
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, staleTime: 0, refetchOnWindowFocus: true },
          mutations: { retry: false },
        },
      }),
  );
  const api = useMemo(() => apiClient(getToken), [getToken]);
  return (
    <QueryClientProvider client={queryClient}>
      <Context.Provider
        value={{
          token: signedIn ? "clerk-session" : "",
          hosted: true,
          signIn: () => {},
          signOut,
          workspace,
          setWorkspace,
          api,
        }}
      >
        {children}
      </Context.Provider>
    </QueryClientProvider>
  );
}

export function useMode() {
  return useQuery({
    queryKey: ["mode"],
    queryFn: async ({ signal }) =>
      unwrap(await apiClient("").GET("/v1/platform/mode", { signal })),
    refetchInterval: 15_000,
  });
}
export function useMe() {
  const { api, token } = useSession();
  return useQuery({
    queryKey: ["me"],
    queryFn: async ({ signal }) => unwrap(await api.GET("/v1/me", { signal })),
    enabled: !!token,
  });
}
