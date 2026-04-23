"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { ApiError, auth } from "@/lib/api";
import type { CurrentUser } from "@/lib/types";

type UserState =
  | { status: "loading" }
  | { status: "authenticated"; user: CurrentUser }
  | { status: "unauthenticated" };

interface UserContextValue {
  state: UserState;
  user: CurrentUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

const UserContext = createContext<UserContextValue>({
  state: { status: "loading" },
  user: null,
  loading: true,
  refresh: async () => {},
});

const CACHE_KEY = "currentUser_v1";

function readCache(): CurrentUser | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.sessionStorage.getItem(CACHE_KEY);
    return raw ? (JSON.parse(raw) as CurrentUser) : null;
  } catch {
    return null;
  }
}

function writeCache(user: CurrentUser): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.sessionStorage.setItem(CACHE_KEY, JSON.stringify(user));
  } catch {}
}

function clearCache(): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.sessionStorage.removeItem(CACHE_KEY);
  } catch {}
}

export function UserProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<UserState>({ status: "loading" });

  const fetchUser = useCallback(async () => {
    try {
      const user = await auth.meQuiet();
      writeCache(user);
      setState({ status: "authenticated", user });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        clearCache();
        setState({ status: "unauthenticated" });
        return;
      }

      const cached = readCache();
      if (cached) {
        setState({ status: "authenticated", user: cached });
      } else {
        setState((current) =>
          current.status === "authenticated" ? current : { status: "loading" },
        );
      }
    }
  }, []);

  useEffect(() => {
    const cached = readCache();
    if (cached) {
      setState({ status: "authenticated", user: cached });
    }
    fetchUser();
  }, [fetchUser]);

  return (
    <UserContext.Provider
      value={{
        state,
        user: state.status === "authenticated" ? state.user : null,
        loading: state.status === "loading",
        refresh: fetchUser,
      }}
    >
      {children}
    </UserContext.Provider>
  );
}

export function useUser(): UserContextValue {
  return useContext(UserContext);
}

export function useCurrentUser(): CurrentUser | null {
  return useContext(UserContext).user;
}
