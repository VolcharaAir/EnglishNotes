-- Disposable PostgreSQL only: keep legacy v1 blobs readable without unbounded pages.
\set ON_ERROR_STOP on
BEGIN;
UPDATE englishnotes_private.cloud_limits SET enabled=true,auth_hook_ready=true,safety_percent=100;
INSERT INTO auth.users VALUES('90000000-0000-0000-0000-000000000001');
INSERT INTO public.lesson_sessions(id,title,created_by)
 VALUES('90000000-0000-0000-0000-000000000002','Legacy payloads','90000000-0000-0000-0000-000000000001');
INSERT INTO public.lesson_members(lesson_id,user_id,role)
 VALUES('90000000-0000-0000-0000-000000000002','90000000-0000-0000-0000-000000000001','student');
INSERT INTO public.lesson_notes(lesson_id,author_id,content)
 SELECT '90000000-0000-0000-0000-000000000002'::uuid,'90000000-0000-0000-0000-000000000001'::uuid,
 repeat('x',1048576) FROM generate_series(1,5);
INSERT INTO public.lesson_notes(lesson_id,author_id,content)
 VALUES('90000000-0000-0000-0000-000000000002','90000000-0000-0000-0000-000000000001',repeat(chr(1),1048576));
CREATE SCHEMA payload_test;
GRANT USAGE ON SCHEMA payload_test TO authenticated;
CREATE FUNCTION payload_test.check_pages() RETURNS void LANGUAGE plpgsql AS $$
DECLARE r jsonb; c bigint:=0; total integer:=0; pages integer:=0; next_c bigint;
BEGIN
 LOOP
  r:=public.en_read(c,64);
  IF r->>'outcome'<>'ok' THEN RAISE EXCEPTION 'Read unexpectedly rejected'; END IF;
  IF octet_length(r::text)>16777216 THEN RAISE EXCEPTION 'Client response cap exceeded'; END IF;
  next_c:=(r->>'cursor')::bigint;
  IF next_c<=c THEN RAISE EXCEPTION 'Cursor failed to advance'; END IF;
  c:=next_c; total:=total+jsonb_array_length(r->'notes'); pages:=pages+1;
  EXIT WHEN NOT (r->>'has_more')::boolean;
  IF pages>6 THEN RAISE EXCEPTION 'Pagination stuck'; END IF;
 END LOOP;
 IF total<>6 OR pages<>3 THEN RAISE EXCEPTION 'Legacy rows lost or oversized page'; END IF;
END $$;
SET LOCAL ROLE authenticated;
SET LOCAL request.jwt.claim.sub='90000000-0000-0000-0000-000000000001';
SELECT payload_test.check_pages();
RESET ROLE;
ROLLBACK;
\echo 'Legacy payload pagination passed: 6 rows, 3 bounded pages, escaped text retained.'
