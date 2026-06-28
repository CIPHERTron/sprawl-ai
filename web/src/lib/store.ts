import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AuthState {
  token: string | null;
  workspaceId: string | null;
  sessionId: string | null;
  isDemo: boolean;
  expiresAt: string | null;

  setDemoSession: (payload: {
    token: string;
    workspaceId: string;
    sessionId: string;
    expiresAt: string;
  }) => void;
  clearSession: () => void;
  isExpired: () => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      workspaceId: null,
      sessionId: null,
      isDemo: false,
      expiresAt: null,

      setDemoSession: ({ token, workspaceId, sessionId, expiresAt }) =>
        set({ token, workspaceId, sessionId, isDemo: true, expiresAt }),

      clearSession: () =>
        set({
          token: null,
          workspaceId: null,
          sessionId: null,
          isDemo: false,
          expiresAt: null,
        }),

      isExpired: () => {
        const { expiresAt } = get();
        if (!expiresAt) return true;
        return new Date(expiresAt) < new Date();
      },
    }),
    { name: "sprawl-auth" }
  )
);
