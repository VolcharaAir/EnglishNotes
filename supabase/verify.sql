-- Read-only checks for Supabase Dashboard -> SQL Editor, AFTER manual application.
SELECT schemaname, tablename, rowsecurity FROM pg_catalog.pg_tables
WHERE schemaname IN ('public','englishnotes_private')
  AND tablename IN ('lesson_sessions','lesson_members','lesson_notes','rpc_limits');

SELECT schemaname, tablename, policyname, cmd, roles
FROM pg_catalog.pg_policies
WHERE schemaname='public' AND tablename IN ('lesson_sessions','lesson_members','lesson_notes')
ORDER BY tablename, policyname;

SELECT
    pg_catalog.has_function_privilege('anon',
        'public.create_lesson_session(text,text,interval)','EXECUTE') AS anon_create_must_be_false,
    pg_catalog.has_function_privilege('anon',
        'public.join_lesson_session(text)','EXECUTE') AS anon_join_must_be_false,
    pg_catalog.has_function_privilege('authenticated',
        'public.join_lesson_session(text)','EXECUTE') AS authenticated_join_must_be_true,
    pg_catalog.has_column_privilege('authenticated','public.lesson_sessions',
        'invitation_code_hash','SELECT') AS hash_read_must_be_false,
    pg_catalog.has_table_privilege('authenticated','public.lesson_members',
        'INSERT') AS direct_membership_insert_must_be_false,
    pg_catalog.has_table_privilege('authenticated','public.lesson_notes',
        'DELETE') AS hard_delete_must_be_false;

SELECT n.nspname, p.proname, p.prosecdef, p.proconfig,
    pg_catalog.pg_get_userbyid(p.proowner) AS owner
FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
WHERE (n.nspname='englishnotes_private') OR
    (n.nspname='public' AND p.proname IN ('create_lesson_session','join_lesson_session'))
ORDER BY n.nspname,p.proname;

SELECT pubname,schemaname,tablename FROM pg_catalog.pg_publication_tables
WHERE pubname='supabase_realtime' AND schemaname='public' AND tablename='lesson_notes';
