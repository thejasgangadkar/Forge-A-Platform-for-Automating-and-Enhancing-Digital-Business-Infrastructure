-- Migration: Add agent_actions and analytics_events tables
-- Run this in Supabase SQL Editor (Dashboard → SQL)

-- Agent tool-calling actions
CREATE TABLE IF NOT EXISTS public.agent_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('book_slot', 'capture_lead', 'escalate')),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Analytics events
CREATE TABLE IF NOT EXISTS public.analytics_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN ('visit', 'chat', 'lead')),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_agent_actions_ws ON public.agent_actions(workspace_id, created_at);
CREATE INDEX IF NOT EXISTS idx_analytics_ws ON public.analytics_events(workspace_id, event_type, created_at);

-- Row Level Security
ALTER TABLE public.agent_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.analytics_events ENABLE ROW LEVEL SECURITY;

-- RLS Policies: users see only their own workspace data
CREATE POLICY "Users see own workspace actions" ON public.agent_actions
    FOR ALL USING (workspace_id IN (SELECT id FROM public.workspaces WHERE user_id = auth.uid()));

CREATE POLICY "Users see own workspace analytics" ON public.analytics_events
    FOR ALL USING (workspace_id IN (SELECT id FROM public.workspaces WHERE user_id = auth.uid()));

-- Allow backend service role to insert (for fire-and-forget tracking)
CREATE POLICY "Service can insert analytics" ON public.analytics_events
    FOR INSERT WITH CHECK (true);

CREATE POLICY "Service can insert actions" ON public.agent_actions
    FOR INSERT WITH CHECK (true);
