import { createContext, useContext, useState, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiUrl } from "@/lib/queryClient";

interface AuthUser {
  userId: string;
  isAdmin: boolean;
  adminPinVerified?: boolean;
  firstName?: string;
  lastName?: string;
  username?: string;
  photoUrl?: string;
}

interface AuthContextType {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  adminPinVerified: boolean;
  isLoading: boolean;
  isBanned: boolean;
  logout: () => Promise<void>;
  refetchSession: () => Promise<any>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  isAuthenticated: false,
  isAdmin: false,
  adminPinVerified: false,
  isLoading: true,
  isBanned: false,
  logout: async () => {},
  refetchSession: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();

  const { data: session, isLoading, refetch } = useQuery<{ authenticated: boolean; banned?: boolean; user?: AuthUser }>({
    queryKey: ["/api/auth/session"],
    queryFn: async () => {
      const res = await fetch(apiUrl("/api/auth/session"), {
        credentials: "include",
        cache: "no-store",
        headers: { "Cache-Control": "no-cache" },
      });
      if (!res.ok) throw new Error("Session fetch failed");
      return res.json();
    },
    refetchOnWindowFocus: true,
    staleTime: 30000,
  });

  const user = session?.authenticated ? session.user || null : null;
  const isBanned = session?.banned === true;

  const logout = useCallback(async () => {
    await fetch(apiUrl("/api/auth/logout"), { method: "POST", credentials: "include" });
    queryClient.invalidateQueries({ queryKey: ["/api/auth/session"] });
  }, [queryClient]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isAdmin: user?.isAdmin || false,
        adminPinVerified: user?.adminPinVerified ?? false,
        isLoading,
        isBanned,
        logout,
        refetchSession: refetch,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
