-- Execute ONLY in a disposable/test database after the migration.
-- SET ROLE tests real PostgreSQL privileges/RLS; the script ends with ROLLBACK.
\set ON_ERROR_STOP on
BEGIN;
CREATE SCHEMA en_test;
GRANT USAGE ON SCHEMA en_test TO anon, authenticated;
CREATE FUNCTION en_test.ok(p_value boolean, p_message text) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
    IF p_value IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'FAILED: %', p_message;
    END IF;
END $$;
CREATE FUNCTION en_test.denied(p_sql text, p_state text, p_message text) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE v_state text;
BEGIN
    BEGIN
        EXECUTE p_sql;
    EXCEPTION WHEN OTHERS THEN
        GET STACKED DIAGNOSTICS v_state = RETURNED_SQLSTATE;
    END;
    PERFORM en_test.ok(v_state = p_state, p_message || ' (SQLSTATE=' || COALESCE(v_state, 'none') || ')');
END $$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA en_test TO anon, authenticated;

INSERT INTO auth.users(id) VALUES
    ('10000000-0000-0000-0000-000000000001'),
    ('10000000-0000-0000-0000-000000000002'),
    ('10000000-0000-0000-0000-000000000003');

SELECT en_test.ok((SELECT pg_catalog.count(*) = 3 FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relname IN ('lesson_sessions','lesson_members','lesson_notes')
    AND c.relrowsecurity), 'all public tables have RLS');
SELECT en_test.ok(NOT pg_catalog.has_function_privilege('anon',
    'public.create_lesson_session(text,text,interval)', 'EXECUTE'), 'anon cannot call create RPC');
SELECT en_test.ok(NOT pg_catalog.has_function_privilege('anon',
    'public.join_lesson_session(text)', 'EXECUTE'), 'anon cannot call join RPC');
SELECT en_test.ok(NOT pg_catalog.has_function_privilege('authenticated',
    'englishnotes_private.consume_rpc_attempt(uuid,text)', 'EXECUTE'), 'limiter is internal');
SELECT en_test.ok((SELECT pg_catalog.count(*) = 5 FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname IN ('public','englishnotes_private') AND p.prosecdef
    AND p.proconfig @> ARRAY['search_path=""']), 'definer functions have empty search_path');
SELECT en_test.ok(EXISTS (SELECT 1 FROM pg_catalog.pg_publication_tables
    WHERE pubname='supabase_realtime' AND schemaname='public' AND tablename='lesson_notes'),
    'notes are in Realtime publication');

SET LOCAL ROLE anon;
SELECT en_test.denied('SELECT id FROM public.lesson_sessions', '42501', 'anon cannot read lessons');
SELECT en_test.denied('SELECT * FROM public.lesson_members', '42501', 'anon cannot read members');
SELECT en_test.denied('SELECT * FROM public.lesson_notes', '42501', 'anon cannot read notes');
SELECT en_test.denied('SELECT * FROM public.create_lesson_session(''forbidden'')', '42501', 'anon RPC');
SELECT en_test.denied('SELECT * FROM public.join_lesson_session(''bad'')', '42501', 'anon join');
RESET ROLE;

SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', '', true);
SELECT en_test.denied('SELECT * FROM public.create_lesson_session(''missing uid'')',
    '42501', 'authenticated without UID cannot create');
SELECT en_test.denied('SELECT * FROM public.join_lesson_session(''bad'')',
    '42501', 'authenticated without UID cannot join');
SELECT set_config('request.jwt.claim.sub', '10000000-0000-0000-0000-000000000001', true);
SELECT en_test.denied('SELECT * FROM public.create_lesson_session('''')', '22023', 'blank title');
SELECT en_test.denied('SELECT * FROM public.create_lesson_session(''x'',''admin'')', '22023', 'invalid role');
SELECT en_test.denied('SELECT * FROM public.create_lesson_session(''x'',''teacher'',interval ''25 hours'')',
    '22023', 'bounded invite expiry');
SELECT lesson_id AS id, invitation_code AS code, outcome
    FROM public.create_lesson_session('English lesson', 'student') \gset lesson_
SELECT en_test.ok(:'lesson_outcome' = 'ok', 'create returns success');
SELECT en_test.ok(:'lesson_code' ~ '^[0-9a-f]{64}$', '256-bit hexadecimal invitation');
SELECT en_test.ok((SELECT pg_catalog.count(*) = 1 FROM public.lesson_members
    WHERE lesson_id = :'lesson_id'::uuid AND role='student'), 'creator membership is automatic');
SELECT en_test.denied('SELECT invitation_code_hash FROM public.lesson_sessions', '42501', 'hash is hidden');
SELECT en_test.denied('SELECT * FROM public.lesson_sessions', '42501', 'no SELECT star leaking hash');
SELECT en_test.denied('INSERT INTO public.lesson_sessions(title,created_by) VALUES(''x'',auth.uid())',
    '42501', 'direct lesson insert forbidden');
SELECT en_test.denied('UPDATE public.lesson_sessions SET status=''closed''', '42501', 'direct status update forbidden');
SELECT en_test.denied('DELETE FROM public.lesson_sessions', '42501', 'direct session delete forbidden');
SELECT en_test.denied('UPDATE public.lesson_members SET role=''teacher''', '42501', 'no role escalation');
SELECT en_test.denied('DELETE FROM public.lesson_members', '42501', 'cannot remove memberships');
SELECT en_test.denied('SELECT * FROM englishnotes_private.rpc_limits', '42501', 'cannot reset attempts');
SELECT en_test.denied('SELECT englishnotes_private.consume_rpc_attempt(auth.uid(),''join'')',
    '42501', 'cannot invoke limiter directly');
INSERT INTO public.lesson_notes(lesson_id,title,content,position)
    VALUES (:'lesson_id'::uuid, 'Vocabulary', 'Original text', 0) RETURNING id \gset note_
SELECT en_test.ok((SELECT author_id=auth.uid() AND revision=1 FROM public.lesson_notes
    WHERE id=:'note_id'::uuid), 'server defaults stamp author and revision');
SELECT en_test.denied(pg_catalog.format(
    'INSERT INTO public.lesson_notes(lesson_id,author_id) VALUES(%L,%L)',
    :'lesson_id','10000000-0000-0000-0000-000000000003'), '42501', 'cannot impersonate an author');
SELECT en_test.denied('UPDATE public.lesson_notes SET created_at=now()', '42501', 'creation time immutable');
SELECT en_test.denied('UPDATE public.lesson_notes SET revision=999', '42501', 'revision server owned');
SELECT en_test.denied('UPDATE public.lesson_notes SET id=gen_random_uuid()', '42501', 'note identity immutable');
SELECT en_test.denied(pg_catalog.format('INSERT INTO public.lesson_notes(lesson_id,position) VALUES(%L,-1)',
    :'lesson_id'), '23514', 'negative position rejected');
SELECT en_test.denied('DELETE FROM public.lesson_notes', '42501', 'no hard deletion');
RESET ROLE;

SELECT en_test.ok((SELECT invitation_code_hash = extensions.digest(:'lesson_code','sha256')
    AND pg_catalog.octet_length(invitation_code_hash)=32 FROM public.lesson_sessions
    WHERE id=:'lesson_id'::uuid), 'only SHA256 digest is persisted');

SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub','10000000-0000-0000-0000-000000000003',true);
SELECT en_test.ok((SELECT pg_catalog.count(*)=0 FROM public.lesson_sessions), 'outsider sees no lessons');
SELECT en_test.ok((SELECT pg_catalog.count(*)=0 FROM public.lesson_members), 'outsider sees no roster');
SELECT en_test.ok((SELECT pg_catalog.count(*)=0 FROM public.lesson_notes), 'outsider sees no notes');
SELECT en_test.ok(NOT englishnotes_private.is_lesson_member(:'lesson_id'::uuid), 'helper uses caller identity');
SELECT en_test.denied(pg_catalog.format('INSERT INTO public.lesson_notes(lesson_id) VALUES(%L)',
    :'lesson_id'), '42501', 'outsider cannot insert notes');
SELECT en_test.denied(pg_catalog.format(
    'INSERT INTO public.lesson_members(lesson_id,user_id,role) VALUES(%L,auth.uid(),''teacher'')',
    :'lesson_id'), '42501', 'outsider cannot insert own membership');
WITH modified AS (UPDATE public.lesson_notes SET content='hacked' WHERE id=:'note_id'::uuid RETURNING id)
    SELECT en_test.ok((SELECT pg_catalog.count(*)=0 FROM modified), 'outsider update affects zero rows');
SELECT en_test.ok((SELECT outcome='invalid_invitation' AND lesson_id IS NULL
    FROM public.join_lesson_session(repeat('0',64))), 'unknown code returns generic failure');
SELECT en_test.ok((SELECT outcome='invalid_invitation' FROM public.join_lesson_session('bad')), 'short code rejected');
SELECT en_test.ok((SELECT outcome='invalid_invitation' FROM public.join_lesson_session(NULL)), 'null code rejected');
SELECT en_test.ok((SELECT outcome='invalid_invitation' FROM public.join_lesson_session(repeat('a',129))), 'oversize code rejected');
SELECT en_test.ok((SELECT outcome='invalid_invitation' FROM public.join_lesson_session('bad')), 'fifth attempt allowed');
SELECT en_test.ok((SELECT outcome='rate_limited' FROM public.join_lesson_session(:'lesson_code')), 'sixth attempt blocked');
RESET ROLE;
SELECT en_test.ok((SELECT attempts=6 FROM englishnotes_private.rpc_limits
    WHERE user_id='10000000-0000-0000-0000-000000000003' AND action='join'), 'failure counters are retained');

SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub','10000000-0000-0000-0000-000000000002',true);
SELECT en_test.ok((SELECT outcome='ok' AND lesson_id=:'lesson_id'::uuid
    FROM public.join_lesson_session(upper(:'lesson_code'))), 'second user joins with normalized code');
SELECT en_test.ok((SELECT pg_catalog.count(*)=2 FROM public.lesson_members
    WHERE lesson_id=:'lesson_id'::uuid), 'exactly two participants');
CREATE TEMP TABLE lesson_members (lesson_id uuid, user_id uuid, role text);
SET LOCAL search_path = pg_temp, public;
SELECT en_test.ok(englishnotes_private.is_lesson_member(:'lesson_id'::uuid),
    'caller search_path and shadow table cannot hijack definer helper');
SELECT en_test.ok(englishnotes_private.can_edit_lesson(:'lesson_id'::uuid),
    'edit helper ignores caller shadow table');
SET LOCAL search_path = public;
SELECT en_test.ok((SELECT role='teacher' FROM public.lesson_members WHERE user_id=auth.uid()), 'opposite role assigned');
UPDATE public.lesson_notes SET title='Shared edit', content='Edited by participant two',position=5
    WHERE id=:'note_id'::uuid;
SELECT en_test.ok((SELECT content='Edited by participant two' AND revision=2
    AND author_id='10000000-0000-0000-0000-000000000001' FROM public.lesson_notes
    WHERE id=:'note_id'::uuid), 'participant two edits participant one note without changing author');
SELECT en_test.denied('UPDATE public.lesson_notes SET author_id=auth.uid()', '42501', 'author immutable');
SELECT en_test.denied(pg_catalog.format('UPDATE public.lesson_notes SET lesson_id=%L',
    :'lesson_id'), '42501', 'lesson identity immutable');
UPDATE public.lesson_notes SET deleted_at=now() WHERE id=:'note_id'::uuid;
SELECT en_test.ok((SELECT deleted_at IS NOT NULL AND revision=3 FROM public.lesson_notes
    WHERE id=:'note_id'::uuid), 'soft deletion keeps a versioned tombstone');
RESET ROLE;
SELECT en_test.ok((SELECT invitation_code_hash IS NULL AND invitation_expires_at IS NULL
    FROM public.lesson_sessions WHERE id=:'lesson_id'::uuid), 'successful join consumes invitation');

-- An attacker cannot reset its own budget. Administrative reset below is TEST setup only.
UPDATE englishnotes_private.rpc_limits SET window_started_at=now()-interval '2 minutes'
    WHERE user_id='10000000-0000-0000-0000-000000000003';
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub','10000000-0000-0000-0000-000000000003',true);
SELECT en_test.ok((SELECT outcome='invalid_invitation' AND lesson_id IS NULL
    FROM public.join_lesson_session(:'lesson_code')), 'third participant cannot reuse a consumed code');
SELECT en_test.ok((SELECT pg_catalog.count(*)=0 FROM public.lesson_notes), 'third user still isolated');
RESET ROLE;

SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub','10000000-0000-0000-0000-000000000001',true);
SELECT lesson_id AS id, invitation_code AS code FROM public.create_lesson_session('Expiring') \gset expired_
SELECT lesson_id AS id, invitation_code AS code FROM public.create_lesson_session('Closed') \gset closed_
SELECT lesson_id AS id, invitation_code AS code FROM public.create_lesson_session('Own other lesson') \gset other_
SELECT lesson_id AS id FROM public.create_lesson_session('Fifth creation') \gset fifth_
SELECT en_test.ok((SELECT outcome='rate_limited' FROM public.create_lesson_session('Sixth creation')), 'create budget limits abuse');
RESET ROLE;
UPDATE public.lesson_sessions SET created_at=now()-interval '2 hours',
    invitation_expires_at=now()-interval '1 hour' WHERE id=:'expired_id'::uuid;
UPDATE public.lesson_sessions SET status='closed' WHERE id=:'closed_id'::uuid OR id=:'lesson_id'::uuid;
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub','10000000-0000-0000-0000-000000000003',true);
SELECT en_test.ok((SELECT outcome='invalid_invitation' FROM public.join_lesson_session(:'expired_code')), 'expired code has generic failure');
SELECT en_test.ok((SELECT outcome='invalid_invitation' FROM public.join_lesson_session(:'closed_code')), 'closed lesson has generic failure');
SELECT set_config('request.jwt.claim.sub','10000000-0000-0000-0000-000000000002',true);
SELECT en_test.ok((SELECT pg_catalog.count(*)=1 FROM public.lesson_sessions), 'member cannot see owner other lessons');
SELECT en_test.ok((SELECT pg_catalog.count(*)=1 FROM public.lesson_notes), 'closed lesson still readable to members');
WITH changed AS (UPDATE public.lesson_notes SET content='closed edit' WHERE id=:'note_id'::uuid RETURNING id)
    SELECT en_test.ok((SELECT pg_catalog.count(*)=0 FROM changed), 'closed lesson is read only');
SELECT en_test.denied(pg_catalog.format('INSERT INTO public.lesson_notes(lesson_id) VALUES(%L)',
    :'lesson_id'), '42501', 'closed lesson rejects new notes');
ROLLBACK;
\echo 'SQL security assertions passed (transaction rolled back).'
