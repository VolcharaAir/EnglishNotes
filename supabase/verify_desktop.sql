-- Read-only verification of manually deployed v2. Never prints keys/invite hashes/IP pepper.
SELECT tablename,rowsecurity FROM pg_tables
WHERE schemaname='public' AND tablename IN('lesson_sessions','lesson_members','lesson_notes');
SELECT enabled,auth_hook_ready,emergency_stop,limited_until,safety_percent,
 requests_user_minute,writes_user_minute,requests_day,writes_day,
 sessions_user_active,sessions_user_total,sessions_total,accounts_total,
 signup_ip_hour,signup_day,note_bytes,notes_session,stored_bytes,egress_day_bytes
FROM englishnotes_private.cloud_limits;
SELECT p.proname,p.prosecdef,p.proconfig,
 has_function_privilege('anon',p.oid,'EXECUTE') AS anon_execute,
 has_function_privilege('authenticated',p.oid,'EXECUTE') AS member_execute
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='public' AND p.proname LIKE 'en_%' ORDER BY 1;
SELECT has_table_privilege('authenticated','public.lesson_notes','SELECT') AS direct_notes_must_be_false,
 has_any_column_privilege('authenticated','public.lesson_notes','UPDATE') AS bypass_update_must_be_false,
 has_function_privilege('supabase_auth_admin','public.en_before_user_created(jsonb)','EXECUTE') AS hook_permission_must_be_true;
SELECT policyname,permissive,cmd FROM pg_policies WHERE schemaname='realtime'
 AND tablename='messages' AND policyname LIKE 'englishnotes_%';
SELECT * FROM pg_publication_tables WHERE pubname='supabase_realtime'
 AND schemaname='public' AND tablename='lesson_notes'; -- expected zero rows in v2
