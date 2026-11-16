-- Forge schema. Safe to re-run.
-- Tables: workspaces, conversations, assets. Auth handled by Supabase Auth.

-- ─── workspaces ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    business_name TEXT NOT NULL,
    business_profile JSONB DEFAULT '{}'::jsonb,
    description TEXT,
    url TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE public.workspaces ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE public.workspaces ADD COLUMN IF NOT EXISTS business_name TEXT;
ALTER TABLE public.workspaces ADD COLUMN IF NOT EXISTS business_profile JSONB DEFAULT '{}'::jsonb;
ALTER TABLE public.workspaces ALTER COLUMN url DROP NOT NULL;

-- ─── conversations ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                 -- 'user' | 'assistant' | 'system'
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conversations_ws ON public.conversations(workspace_id, created_at);

-- ─── assets ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE,
    type TEXT NOT NULL,                 -- 'website' | 'agent'
    name TEXT,
    path TEXT,
    config JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_assets_ws ON public.assets(workspace_id);

-- ─── Row Level Security ─────────────────────────────────────
ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assets ENABLE ROW LEVEL SECURITY;

-- Users can only see/modify their own workspaces.
DROP POLICY IF EXISTS "own_workspaces" ON public.workspaces;
CREATE POLICY "own_workspaces" ON public.workspaces
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Conversations/assets accessible if the parent workspace belongs to the user.
DROP POLICY IF EXISTS "own_conversations" ON public.conversations;
CREATE POLICY "own_conversations" ON public.conversations
    FOR ALL USING (
        EXISTS (SELECT 1 FROM public.workspaces w
                WHERE w.id = workspace_id AND w.user_id = auth.uid())
    ) WITH CHECK (
        EXISTS (SELECT 1 FROM public.workspaces w
                WHERE w.id = workspace_id AND w.user_id = auth.uid())
    );

DROP POLICY IF EXISTS "own_assets" ON public.assets;
CREATE POLICY "own_assets" ON public.assets
    FOR ALL USING (
        EXISTS (SELECT 1 FROM public.workspaces w
                WHERE w.id = workspace_id AND w.user_id = auth.uid())
    ) WITH CHECK (
        EXISTS (SELECT 1 FROM public.workspaces w
                WHERE w.id = workspace_id AND w.user_id = auth.uid())
    );

-- Service role (backend) bypasses RLS automatically.
