-- Test database only. No real credentials; impersonation is a PostgreSQL RLS fixture, not JWT testing.
\set ON_ERROR_STOP on
BEGIN;
CREATE SCHEMA test_desktop;
GRANT USAGE ON SCHEMA test_desktop TO authenticated,anon,supabase_auth_admin;
CREATE FUNCTION test_desktop.ok(v boolean,message text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN IF v IS DISTINCT FROM true THEN RAISE EXCEPTION 'FAILED: %',message; END IF; END $$;
CREATE FUNCTION test_desktop.denied(q text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE code text;
BEGIN
 BEGIN EXECUTE q; EXCEPTION WHEN OTHERS THEN GET STACKED DIAGNOSTICS code=RETURNED_SQLSTATE; END;
 PERFORM test_desktop.ok(code='42501','expected permission denial');
END $$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA test_desktop TO authenticated,anon,supabase_auth_admin;
INSERT INTO auth.users VALUES('10000000-0000-0000-0000-000000000001'),
 ('10000000-0000-0000-0000-000000000002'),('10000000-0000-0000-0000-000000000003');
SET LOCAL ROLE authenticated;
SET LOCAL request.jwt.claim.sub='10000000-0000-0000-0000-000000000001';
SELECT test_desktop.ok(public.en_create_session('20000000-0000-0000-0000-000000000001','x')->>'outcome'='cloud_paused','default closed');
RESET ROLE;
UPDATE englishnotes_private.cloud_limits SET enabled=true,auth_hook_ready=true,safety_percent=100;
SET LOCAL ROLE authenticated;
SET LOCAL request.jwt.claim.sub='10000000-0000-0000-0000-000000000001';
SELECT public.en_create_session('20000000-0000-0000-0000-000000000001','First')->>'invitation_code' AS code \gset
SELECT test_desktop.ok(public.en_create_session('20000000-0000-0000-0000-000000000001','retry')->>'outcome'='ok','idempotent create');
-- Retry reissues an unconsumed invitation. Read the latest code, without extending its lifetime.
SELECT public.en_create_session('20000000-0000-0000-0000-000000000001','retry')->>'invitation_code' AS code \gset
SELECT test_desktop.denied('SELECT id FROM public.lesson_sessions');
SELECT test_desktop.denied('SELECT * FROM public.lesson_notes');
SELECT test_desktop.denied('SELECT * FROM public.create_lesson_session(''bypass'')');
SELECT test_desktop.denied('SELECT * FROM public.en_before_user_created(''{}'')');
SET LOCAL request.jwt.claim.sub='10000000-0000-0000-0000-000000000002';
SELECT test_desktop.ok(public.en_join_session(:'code','30000000-0000-0000-0000-000000000001')->>'outcome'='ok','join');
SELECT test_desktop.ok(public.en_join_session('wrong','30000000-0000-0000-0000-000000000001')->>'outcome'='ok','lost join response recovery');
SELECT test_desktop.ok(public.en_finish_session('20000000-0000-0000-0000-000000000001')->>'outcome'='forbidden','peer cannot close');
SET LOCAL request.jwt.claim.sub='10000000-0000-0000-0000-000000000003';
SELECT test_desktop.ok(public.en_join_session(:'code',gen_random_uuid())->>'outcome'='invalid_invitation','third user denied');
SELECT test_desktop.ok(jsonb_array_length(public.en_read()->'notes')=0,'outsider read');
SELECT test_desktop.ok(public.en_write_note(gen_random_uuid(),gen_random_uuid(),
 '20000000-0000-0000-0000-000000000001',0,'n','x',0)->>'outcome'='forbidden','outsider write');
SET LOCAL request.jwt.claim.sub='10000000-0000-0000-0000-000000000001';
SELECT test_desktop.ok(public.en_read(0,NULL)->>'outcome'='invalid_input','NULL cannot bypass page cap');
SELECT test_desktop.ok(public.en_write_note('40000000-0000-0000-0000-000000000001',
 '50000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001',0,'n','original',0)->>'outcome'='ok','write');
SELECT test_desktop.ok((public.en_write_note('40000000-0000-0000-0000-000000000001',
 '50000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001',0,'n','original',0)->'note'->>'revision')::int=1,'write idempotency');
SET LOCAL request.jwt.claim.sub='10000000-0000-0000-0000-000000000002';
SELECT test_desktop.ok(public.en_write_note(gen_random_uuid(),
 '50000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001',1,'n','peer edit',0)->>'outcome'='ok','shared edit');
SET LOCAL request.jwt.claim.sub='10000000-0000-0000-0000-000000000001';
SELECT test_desktop.ok(public.en_write_note(gen_random_uuid(),
 '50000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001',1,'n','stale',0)->>'outcome'='conflict','stale version refused');
SELECT test_desktop.ok(public.en_write_note(gen_random_uuid(),gen_random_uuid(),
 '20000000-0000-0000-0000-000000000001',0,'n',repeat('x',16385),0)->>'outcome'='note_too_large_or_invalid','size cap');
SELECT test_desktop.ok(public.en_finish_session('20000000-0000-0000-0000-000000000001')->>'outcome'='ok','owner close');
SELECT test_desktop.ok(public.en_write_note(gen_random_uuid(),
 '50000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001',2,'n','closed',0)->>'outcome'='session_closed','closed read only');
SELECT set_config('test.realtime_topic','lesson:20000000-0000-0000-0000-000000000001',true);
SELECT test_desktop.ok((SELECT count(*)>0 FROM realtime.messages),'member can receive hint');
SET LOCAL request.jwt.claim.sub='10000000-0000-0000-0000-000000000003';
SELECT test_desktop.ok((SELECT count(*)=0 FROM realtime.messages),'outsider cannot receive hint');
RESET ROLE;
DELETE FROM englishnotes_private.cloud_usage;
UPDATE englishnotes_private.cloud_limits SET signup_ip_hour=1;
SET LOCAL ROLE supabase_auth_admin;
SELECT test_desktop.ok(public.en_before_user_created('{"metadata":{"ip_address":"192.0.2.1"},"user":{}}')='{}','trusted hook signup');
SELECT test_desktop.ok(public.en_before_user_created('{"metadata":{"ip_address":"192.0.2.1"},"user":{}}') ? 'error','IP quota');
SELECT test_desktop.ok(public.en_before_user_created('{"metadata":{},"user":{}}') ? 'error','missing IP fails closed');
RESET ROLE;
DELETE FROM englishnotes_private.cloud_usage;
UPDATE englishnotes_private.cloud_limits SET signup_ip_hour=100,signup_day=1;
SET LOCAL ROLE supabase_auth_admin;
SELECT test_desktop.ok(public.en_before_user_created('{"metadata":{"ip_address":"192.0.2.10"},"user":{}}')='{}','signup global first');
SELECT test_desktop.ok(public.en_before_user_created('{"metadata":{"ip_address":"192.0.2.11"},"user":{}}') ? 'error','signup global cap');
RESET ROLE;
SELECT test_desktop.ok((SELECT count(*) FROM englishnotes_private.cloud_usage WHERE scope LIKE 'signup-ip:%')=1,'exhausted signup does not allocate another IP bucket');
DELETE FROM englishnotes_private.cloud_usage;
UPDATE englishnotes_private.cloud_limits SET signup_ip_hour=1,signup_day=100;
SET LOCAL ROLE supabase_auth_admin;
SELECT test_desktop.ok(public.en_before_user_created('{"metadata":{"ip_address":"2001:db8::1"},"user":{}}')='{}','IPv6 first');
SELECT test_desktop.ok(public.en_before_user_created('{"metadata":{"ip_address":"2001:db8::2"},"user":{}}') ? 'error','IPv6 subnet grouped');
RESET ROLE;
UPDATE englishnotes_private.cloud_limits SET accounts_total=1;
SET LOCAL ROLE supabase_auth_admin;
SELECT test_desktop.ok(public.en_before_user_created('{"metadata":{"ip_address":"192.0.2.99"},"user":{}}') ? 'error','global account cap');
RESET ROLE;
UPDATE englishnotes_private.cloud_limits SET accounts_total=1000,emergency_stop=true;
SET LOCAL ROLE authenticated;
SELECT test_desktop.ok(public.en_read()->>'outcome'='cloud_paused','emergency stop');
RESET ROLE;
UPDATE englishnotes_private.cloud_limits SET emergency_stop=false,sessions_total=1;
SET LOCAL ROLE authenticated;
SELECT test_desktop.ok(public.en_create_session(gen_random_uuid(),'over cap')->>'outcome'='session_limit','global session cap');
RESET ROLE;
UPDATE englishnotes_private.cloud_limits SET sessions_total=1000;
DELETE FROM englishnotes_private.cloud_usage;
SET LOCAL ROLE authenticated;
SET LOCAL request.jwt.claim.sub='10000000-0000-0000-0000-000000000001';
SELECT public.en_create_session('20000000-0000-0000-0000-000000000099','Quota')->>'invitation_code' AS expired_code \gset
RESET ROLE;
UPDATE public.lesson_sessions SET created_at=clock_timestamp()-interval '1 day',
 invitation_expires_at=clock_timestamp()-interval '1 second'
 WHERE id='20000000-0000-0000-0000-000000000099';
UPDATE englishnotes_private.cloud_limits SET notes_session=1;
SET LOCAL ROLE authenticated;
SET LOCAL request.jwt.claim.sub='10000000-0000-0000-0000-000000000003';
SELECT test_desktop.ok(public.en_join_session(:'expired_code',gen_random_uuid())->>'outcome'='invalid_invitation','expired invite denied');
SET LOCAL request.jwt.claim.sub='10000000-0000-0000-0000-000000000001';
SELECT test_desktop.ok(public.en_write_note(gen_random_uuid(),'50000000-0000-0000-0000-000000000099',
 '20000000-0000-0000-0000-000000000099',0,'n','first',0)->>'outcome'='ok','quota initial note');
SELECT test_desktop.ok(public.en_write_note(gen_random_uuid(),gen_random_uuid(),
 '20000000-0000-0000-0000-000000000099',0,'n','overflow',1)->>'outcome'='note_limit','note count quota');
RESET ROLE;
UPDATE englishnotes_private.cloud_limits SET stored_bytes=1;
SET LOCAL ROLE authenticated;
SELECT test_desktop.ok(public.en_write_note(gen_random_uuid(),'50000000-0000-0000-0000-000000000099',
 '20000000-0000-0000-0000-000000000099',1,'n','over storage',0)->>'outcome'='storage_budget_exhausted','storage quota');
RESET ROLE;
UPDATE englishnotes_private.cloud_limits SET stored_bytes=16777216,notes_session=250,sessions_user_active=1;
SET LOCAL ROLE authenticated;
SELECT test_desktop.ok(public.en_create_session(gen_random_uuid(),'Active overflow')->>'outcome'='session_limit','active membership cap');
RESET ROLE;
DELETE FROM englishnotes_private.cloud_usage;
UPDATE englishnotes_private.cloud_limits SET sessions_user_active=3,writes_day=1;
SET LOCAL ROLE authenticated;
SELECT test_desktop.ok(public.en_write_note(gen_random_uuid(),'50000000-0000-0000-0000-000000000099',
 '20000000-0000-0000-0000-000000000099',1,'n','within daily writes',0)->>'outcome'='ok','global write first');
SELECT test_desktop.ok(public.en_write_note(gen_random_uuid(),'50000000-0000-0000-0000-000000000099',
 '20000000-0000-0000-0000-000000000099',2,'n','over daily writes',0)->>'outcome'='budget_exhausted','global write circuit');
RESET ROLE;
UPDATE englishnotes_private.cloud_limits SET writes_day=2000,limited_until=NULL;
DELETE FROM englishnotes_private.cloud_usage;
UPDATE englishnotes_private.cloud_limits SET requests_user_minute=1;
SET LOCAL ROLE authenticated;
SET LOCAL request.jwt.claim.sub='10000000-0000-0000-0000-000000000001';
SELECT test_desktop.ok(public.en_read()->>'outcome'='ok','first read');
SELECT test_desktop.ok(public.en_read()->>'outcome'='rate_limited','per user rate');
RESET ROLE;
DELETE FROM englishnotes_private.cloud_usage;
UPDATE englishnotes_private.cloud_limits SET requests_user_minute=100,egress_day_bytes=1;
SET LOCAL ROLE authenticated;
SELECT test_desktop.ok(public.en_read()->>'outcome'='budget_exhausted','egress circuit');
SELECT test_desktop.ok((public.en_status()->>'enabled')::boolean=false,'budget circuit active');
RESET ROLE;
ROLLBACK;
\echo 'Desktop SQL contracts passed.'
