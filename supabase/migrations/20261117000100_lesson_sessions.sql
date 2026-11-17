-- EnglishNotes: first cloud schema. Apply MANUALLY; no SQLite or client changes.
-- Requires Supabase auth.users, auth.uid(), anon/authenticated roles and postgres ownership.
BEGIN;

CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
DO $precondition$
BEGIN
    IF (SELECT n.nspname FROM pg_catalog.pg_extension e
        JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace
        WHERE e.extname = 'pgcrypto') <> 'extensions' THEN
        RAISE EXCEPTION 'pgcrypto must be installed in the extensions schema';
    END IF;
END
$precondition$;

CREATE SCHEMA englishnotes_private;
REVOKE ALL ON SCHEMA englishnotes_private FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA englishnotes_private TO authenticated;

CREATE TABLE public.lesson_sessions (
    id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    title text NOT NULL CHECK (pg_catalog.char_length(title) BETWEEN 1 AND 200),
    created_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    invitation_code_hash bytea UNIQUE,
    created_at timestamptz NOT NULL DEFAULT pg_catalog.now(),
    invitation_expires_at timestamptz,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed')),
    CHECK (invitation_code_hash IS NULL OR pg_catalog.octet_length(invitation_code_hash) = 32),
    CHECK ((invitation_code_hash IS NULL) = (invitation_expires_at IS NULL)),
    CHECK (invitation_expires_at IS NULL OR invitation_expires_at > created_at)
);

CREATE TABLE public.lesson_members (
    lesson_id uuid NOT NULL REFERENCES public.lesson_sessions(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('teacher', 'student')),
    joined_at timestamptz NOT NULL DEFAULT pg_catalog.now(),
    PRIMARY KEY (lesson_id, user_id),
    UNIQUE (lesson_id, role) -- two roles, one person per role: at most two participants
);
CREATE INDEX lesson_members_by_user ON public.lesson_members(user_id, lesson_id);

CREATE TABLE public.lesson_notes (
    id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    lesson_id uuid NOT NULL REFERENCES public.lesson_sessions(id) ON DELETE CASCADE,
    author_id uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE RESTRICT,
    title text NOT NULL DEFAULT '' CHECK (pg_catalog.char_length(title) <= 200),
    content text NOT NULL DEFAULT '' CHECK (pg_catalog.octet_length(content) <= 1048576),
    position bigint NOT NULL DEFAULT 0 CHECK (position >= 0),
    created_at timestamptz NOT NULL DEFAULT pg_catalog.now(),
    updated_at timestamptz NOT NULL DEFAULT pg_catalog.now(),
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    deleted_at timestamptz
);
CREATE INDEX lesson_notes_by_lesson ON public.lesson_notes(lesson_id, position, id);

-- Durable per-identity budgets. These are not an IP/global/Sybil rate limiter.
CREATE TABLE englishnotes_private.rpc_limits (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    action text NOT NULL CHECK (action IN ('create', 'join')),
    window_started_at timestamptz NOT NULL,
    attempts integer NOT NULL CHECK (attempts > 0),
    PRIMARY KEY (user_id, action)
);

ALTER TABLE public.lesson_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lesson_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lesson_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE englishnotes_private.rpc_limits ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.lesson_sessions, public.lesson_members, public.lesson_notes
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON englishnotes_private.rpc_limits FROM PUBLIC, anon, authenticated;

-- Deliberately exclude the hash. Future clients must select explicit session columns, not '*'.
GRANT SELECT (id, title, created_by, created_at, invitation_expires_at, status)
    ON public.lesson_sessions TO authenticated;
GRANT SELECT ON public.lesson_members, public.lesson_notes TO authenticated;
GRANT INSERT (id, lesson_id, author_id, title, content, position)
    ON public.lesson_notes TO authenticated;
GRANT UPDATE (title, content, position, deleted_at) ON public.lesson_notes TO authenticated;
-- No direct membership/session writes and no physical note DELETE.

-- Definer helpers avoid recursive RLS on lesson_members. They only inspect auth.uid().
CREATE FUNCTION englishnotes_private.is_lesson_member(p_lesson_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.lesson_members m
        WHERE m.lesson_id = p_lesson_id AND m.user_id = (SELECT auth.uid())
    );
$function$;

CREATE FUNCTION englishnotes_private.can_edit_lesson(p_lesson_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.lesson_members m
        JOIN public.lesson_sessions s ON s.id = m.lesson_id
        WHERE m.lesson_id = p_lesson_id AND m.user_id = (SELECT auth.uid())
          AND s.status = 'active'
    );
$function$;

REVOKE ALL ON FUNCTION englishnotes_private.is_lesson_member(uuid),
    englishnotes_private.can_edit_lesson(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION englishnotes_private.is_lesson_member(uuid),
    englishnotes_private.can_edit_lesson(uuid) TO authenticated;

CREATE POLICY sessions_read_members ON public.lesson_sessions FOR SELECT TO authenticated
    USING (englishnotes_private.is_lesson_member(id));
CREATE POLICY members_read_same_lesson ON public.lesson_members FOR SELECT TO authenticated
    USING (englishnotes_private.is_lesson_member(lesson_id));
CREATE POLICY notes_read_members ON public.lesson_notes FOR SELECT TO authenticated
    USING (englishnotes_private.is_lesson_member(lesson_id));
CREATE POLICY notes_insert_members ON public.lesson_notes FOR INSERT TO authenticated
    WITH CHECK (author_id = (SELECT auth.uid())
                AND englishnotes_private.can_edit_lesson(lesson_id));
CREATE POLICY notes_update_members ON public.lesson_notes FOR UPDATE TO authenticated
    USING (englishnotes_private.can_edit_lesson(lesson_id))
    WITH CHECK (englishnotes_private.can_edit_lesson(lesson_id));

CREATE FUNCTION englishnotes_private.consume_rpc_attempt(p_user_id uuid, p_action text)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $function$
DECLARE
    v_count integer;
    v_now timestamptz := pg_catalog.clock_timestamp();
BEGIN
    INSERT INTO englishnotes_private.rpc_limits AS budget
        (user_id, action, window_started_at, attempts)
    VALUES (p_user_id, p_action, v_now, 1)
    ON CONFLICT (user_id, action) DO UPDATE SET
        attempts = CASE WHEN budget.window_started_at <= v_now - interval '1 minute'
                        THEN 1 ELSE LEAST(budget.attempts + 1, 1000000) END,
        window_started_at = CASE WHEN budget.window_started_at <= v_now - interval '1 minute'
                                 THEN v_now ELSE budget.window_started_at END
    RETURNING attempts INTO v_count;
    RETURN v_count <= 5;
END;
$function$;
REVOKE ALL ON FUNCTION englishnotes_private.consume_rpc_attempt(uuid, text)
    FROM PUBLIC, anon, authenticated;

CREATE FUNCTION englishnotes_private.stamp_lesson_note()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $function$
BEGIN
    NEW.updated_at := pg_catalog.clock_timestamp();
    IF TG_OP = 'INSERT' THEN
        NEW.created_at := NEW.updated_at;
        NEW.revision := 1;
    ELSE
        NEW.revision := OLD.revision + 1;
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION englishnotes_private.stamp_lesson_note()
    FROM PUBLIC, anon, authenticated;
CREATE TRIGGER stamp_lesson_note BEFORE INSERT OR UPDATE ON public.lesson_notes
    FOR EACH ROW EXECUTE FUNCTION englishnotes_private.stamp_lesson_note();

-- The plaintext code is returned only once to the creator and is never stored.
CREATE FUNCTION public.create_lesson_session(
    p_title text,
    p_creator_role text DEFAULT 'student',
    p_invitation_ttl interval DEFAULT interval '30 minutes'
)
RETURNS TABLE (lesson_id uuid, invitation_code text, invitation_expires_at timestamptz, outcome text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $function$
DECLARE
    v_user uuid := auth.uid();
    v_id uuid;
    v_code text;
    v_expires timestamptz;
BEGIN
    IF v_user IS NULL THEN
        RAISE EXCEPTION 'Authentication required' USING ERRCODE = '42501';
    END IF;
    IF p_title IS NULL OR pg_catalog.char_length(pg_catalog.btrim(p_title)) NOT BETWEEN 1 AND 200
       OR p_creator_role IS NULL OR p_creator_role NOT IN ('teacher', 'student')
       OR p_invitation_ttl IS NULL
       OR p_invitation_ttl NOT BETWEEN interval '1 minute' AND interval '24 hours' THEN
        RAISE EXCEPTION 'Invalid lesson parameters' USING ERRCODE = '22023';
    END IF;
    IF NOT englishnotes_private.consume_rpc_attempt(v_user, 'create') THEN
        RETURN QUERY SELECT NULL::uuid, NULL::text, NULL::timestamptz, 'rate_limited'::text;
        RETURN;
    END IF;
    v_code := pg_catalog.encode(extensions.gen_random_bytes(32), 'hex');
    v_expires := pg_catalog.clock_timestamp() + p_invitation_ttl;
    INSERT INTO public.lesson_sessions
        (title, created_by, invitation_code_hash, invitation_expires_at)
    VALUES (pg_catalog.btrim(p_title), v_user, extensions.digest(v_code, 'sha256'), v_expires)
    RETURNING id INTO v_id;
    INSERT INTO public.lesson_members (lesson_id, user_id, role)
    VALUES (v_id, v_user, p_creator_role);
    RETURN QUERY SELECT v_id, v_code, v_expires, 'ok'::text;
END;
$function$;

CREATE FUNCTION public.join_lesson_session(p_invitation_code text)
RETURNS TABLE (lesson_id uuid, outcome text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $function$
DECLARE
    v_user uuid := auth.uid();
    v_code text;
    v_session public.lesson_sessions%ROWTYPE;
    v_count bigint;
    v_role text;
BEGIN
    IF v_user IS NULL THEN
        RAISE EXCEPTION 'Authentication required' USING ERRCODE = '42501';
    END IF;
    -- Return failures rather than raise: exceptions would roll back the attempt counter.
    IF NOT englishnotes_private.consume_rpc_attempt(v_user, 'join') THEN
        RETURN QUERY SELECT NULL::uuid, 'rate_limited'::text;
        RETURN;
    END IF;
    IF p_invitation_code IS NULL OR pg_catalog.octet_length(p_invitation_code) > 128 THEN
        RETURN QUERY SELECT NULL::uuid, 'invalid_invitation'::text;
        RETURN;
    END IF;
    v_code := pg_catalog.lower(pg_catalog.btrim(p_invitation_code));
    IF v_code !~ '^[0-9a-f]{64}$' THEN
        RETURN QUERY SELECT NULL::uuid, 'invalid_invitation'::text;
        RETURN;
    END IF;
    SELECT s.* INTO v_session FROM public.lesson_sessions s
    WHERE s.invitation_code_hash = extensions.digest(v_code, 'sha256') FOR UPDATE;
    IF NOT FOUND THEN
        RETURN QUERY SELECT NULL::uuid, 'invalid_invitation'::text;
        RETURN;
    END IF;
    -- Check time after acquiring the row lock; a blocked request can outlive the invite.
    IF v_session.status <> 'active'
       OR v_session.invitation_expires_at <= pg_catalog.clock_timestamp() THEN
        RETURN QUERY SELECT NULL::uuid, 'invalid_invitation'::text;
        RETURN;
    END IF;
    SELECT pg_catalog.count(*) INTO v_count FROM public.lesson_members m
    WHERE m.lesson_id = v_session.id;
    IF v_count <> 1 OR EXISTS (
        SELECT 1 FROM public.lesson_members m
        WHERE m.lesson_id = v_session.id AND m.user_id = v_user
    ) THEN
        RETURN QUERY SELECT NULL::uuid, 'invalid_invitation'::text;
        RETURN;
    END IF;
    SELECT CASE WHEN m.role = 'teacher' THEN 'student' ELSE 'teacher' END
    INTO v_role FROM public.lesson_members m WHERE m.lesson_id = v_session.id;
    INSERT INTO public.lesson_members (lesson_id, user_id, role)
    VALUES (v_session.id, v_user, v_role);
    UPDATE public.lesson_sessions SET invitation_code_hash = NULL, invitation_expires_at = NULL
    WHERE id = v_session.id;
    RETURN QUERY SELECT v_session.id, 'ok'::text;
END;
$function$;

REVOKE ALL ON FUNCTION public.create_lesson_session(text, text, interval),
    public.join_lesson_session(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_lesson_session(text, text, interval),
    public.join_lesson_session(text) TO authenticated;

-- UPDATE tombstones provide RLS-filterable events; clients cannot hard-delete notes.
ALTER TABLE public.lesson_notes REPLICA IDENTITY DEFAULT;
DO $realtime$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_publication WHERE pubname = 'supabase_realtime') THEN
        CREATE PUBLICATION supabase_realtime;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_publication WHERE pubname = 'supabase_realtime' AND puballtables
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND schemaname = 'public' AND tablename = 'lesson_notes'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.lesson_notes;
    END IF;
END
$realtime$;

COMMIT;
