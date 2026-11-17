-- READ ONLY. Run as postgres in the target project's Dashboard SQL Editor.
-- Export this one result as JSON to work/supabase-applied-schema.json.
-- Contains definitions/ACL only: no users, notes, invitation values, keys or JWTs.
SELECT jsonb_build_object(
  'format_version', 1,
  'server_version', current_setting('server_version'),
  'functions', (
    SELECT jsonb_agg(jsonb_build_object(
      'schema', n.nspname, 'name', p.proname,
      'input_args', COALESCE(to_jsonb(p.proargnames[1:p.pronargs]), '[]'::jsonb),
      'identity_args', pg_get_function_identity_arguments(p.oid),
      'input_types', oidvectortypes(p.proargtypes),
      'result', pg_get_function_result(p.oid),
      'body', p.prosrc, 'definition', pg_get_functiondef(p.oid),
      'security_definer', p.prosecdef, 'settings', p.proconfig,
      'owner', pg_get_userbyid(p.proowner),
      'execute_anon', has_function_privilege('anon',p.oid,'EXECUTE'),
      'execute_authenticated', has_function_privilege('authenticated',p.oid,'EXECUTE')
    ) ORDER BY n.nspname,p.proname,p.oid)
    FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname='englishnotes_private' OR
      (n.nspname='public' AND p.proname IN ('create_lesson_session','join_lesson_session'))
  ),
  'tables', (
    SELECT jsonb_agg(jsonb_build_object(
      'schema', n.nspname, 'name', c.relname, 'rls', c.relrowsecurity,
      'columns', (SELECT jsonb_agg(jsonb_build_object(
        'name', a.attname, 'type', format_type(a.atttypid,a.atttypmod),
        'not_null', a.attnotnull,
        'default', pg_get_expr(d.adbin,d.adrelid),
        'select_authenticated', has_column_privilege('authenticated',c.oid,a.attnum,'SELECT'),
        'insert_authenticated', has_column_privilege('authenticated',c.oid,a.attnum,'INSERT'),
        'update_authenticated', has_column_privilege('authenticated',c.oid,a.attnum,'UPDATE')
      ) ORDER BY a.attnum) FROM pg_attribute a
        LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped),
      'constraints', (SELECT jsonb_agg(pg_get_constraintdef(k.oid) ORDER BY k.conname)
                      FROM pg_constraint k WHERE k.conrelid=c.oid),
      'policies', (SELECT jsonb_agg(to_jsonb(v) ORDER BY v.policyname)
                   FROM pg_policies v WHERE v.schemaname=n.nspname AND v.tablename=c.relname),
      'select_anon', has_any_column_privilege('anon',c.oid,'SELECT'),
      'delete_authenticated', has_table_privilege('authenticated',c.oid,'DELETE')
    ) ORDER BY n.nspname,c.relname)
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE c.relkind='r' AND (
      (n.nspname='public' AND c.relname IN ('lesson_sessions','lesson_members','lesson_notes'))
      OR (n.nspname='englishnotes_private' AND c.relname='rpc_limits'))
  )
) AS schema_snapshot;
