'use client';
import { create } from 'zustand';
import { supabase } from './supabase';

export const useAuth = create((set) => ({
  user: null,
  loading: true,
  setUser: (user) => set({ user, loading: false }),
  signOut: async () => {
    await supabase.auth.signOut();
    set({ user: null });
  },
}));

// Initialise session listener once (client-side).
if (typeof window !== 'undefined') {
  supabase.auth.getSession().then(({ data }) => {
    useAuth.getState().setUser(data?.session?.user || null);
  });
  supabase.auth.onAuthStateChange((_event, session) => {
    useAuth.getState().setUser(session?.user || null);
  });
}
