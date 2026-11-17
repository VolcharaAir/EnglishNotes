-- MANUAL migration. Retains v1 rows; changes the public API to bounded v2 RPCs.
BEGIN;
CREATE TABLE englishnotes_private.cloud_limits (
 id boolean PRIMARY KEY DEFAULT true CHECK(id),
 enabled boolean NOT NULL DEFAULT false,
 auth_hook_ready boolean NOT NULL DEFAULT false,
 emergency_stop boolean NOT NULL DEFAULT false,
 limited_until timestamptz,
 safety_percent integer NOT NULL DEFAULT 80 CHECK(safety_percent BETWEEN 1 AND 100),
 requests_user_minute integer NOT NULL DEFAULT 120 CHECK(requests_user_minute>0),
 requests_day integer NOT NULL DEFAULT 30000 CHECK(requests_day>0),
 writes_user_minute integer NOT NULL DEFAULT 20 CHECK(writes_user_minute>0),
 sessions_user_day integer NOT NULL DEFAULT 10 CHECK(sessions_user_day>0),
 sessions_day integer NOT NULL DEFAULT 200 CHECK(sessions_day>0),
 sessions_total integer NOT NULL DEFAULT 1000 CHECK(sessions_total>0),
 accounts_total integer NOT NULL DEFAULT 1000 CHECK(accounts_total>0),
 invitation_minutes integer NOT NULL DEFAULT 30 CHECK(invitation_minutes BETWEEN 1 AND 1440),
 writes_day integer NOT NULL DEFAULT 2000 CHECK(writes_day>0),
 maintenance_at timestamptz,
 sessions_user_total integer NOT NULL DEFAULT 100 CHECK(sessions_user_total>0),
 sessions_user_active integer NOT NULL DEFAULT 3 CHECK(sessions_user_active>0),
 note_bytes integer NOT NULL DEFAULT 16384 CHECK(note_bytes BETWEEN 1 AND 1048576),
 notes_session integer NOT NULL DEFAULT 250 CHECK(notes_session>0),
 stored_bytes bigint NOT NULL DEFAULT 16777216 CHECK(stored_bytes>0),
 egress_day_bytes bigint NOT NULL DEFAULT 67108864 CHECK(egress_day_bytes>0),
 signup_ip_hour integer NOT NULL DEFAULT 30 CHECK(signup_ip_hour>0),
 signup_day integer NOT NULL DEFAULT 100 CHECK(signup_day>0),
 ip_pepper bytea NOT NULL DEFAULT extensions.gen_random_bytes(32)
);
INSERT INTO englishnotes_private.cloud_limits DEFAULT VALUES;
CREATE TABLE englishnotes_private.cloud_usage (
 scope text NOT NULL, bucket timestamptz NOT NULL, amount bigint NOT NULL CHECK(amount>=0),
 PRIMARY KEY(scope,bucket)
);
CREATE INDEX cloud_usage_by_bucket ON englishnotes_private.cloud_usage(bucket);
CREATE TABLE englishnotes_private.note_receipts (
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 operation_id uuid NOT NULL, response jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,operation_id)
);
ALTER TABLE englishnotes_private.cloud_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE englishnotes_private.cloud_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE englishnotes_private.note_receipts ENABLE ROW LEVEL SECURITY;
CREATE TABLE englishnotes_private.join_receipts (
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 operation_id uuid NOT NULL, lesson_id uuid NOT NULL REFERENCES public.lesson_sessions(id) ON DELETE CASCADE,
 PRIMARY KEY(user_id,operation_id)
);
ALTER TABLE englishnotes_private.join_receipts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON englishnotes_private.join_receipts FROM PUBLIC,anon,authenticated;
REVOKE ALL ON englishnotes_private.cloud_limits,englishnotes_private.cloud_usage,
 englishnotes_private.note_receipts FROM PUBLIC,anon,authenticated;

CREATE SEQUENCE englishnotes_private.change_sequence;
ALTER TABLE public.lesson_notes ADD COLUMN sync_seq bigint NOT NULL
 DEFAULT nextval('englishnotes_private.change_sequence');
CREATE INDEX notes_sync_sequence ON public.lesson_notes(sync_seq);
CREATE FUNCTION englishnotes_private.advance_sequence() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$ BEGIN
 NEW.sync_seq:=nextval('englishnotes_private.change_sequence'); RETURN NEW;
END $$;
CREATE TRIGGER advance_note_sequence BEFORE UPDATE ON public.lesson_notes
 FOR EACH ROW EXECUTE FUNCTION englishnotes_private.advance_sequence();

CREATE FUNCTION englishnotes_private.tick(p_scope text,p_bucket timestamptz,p_amount bigint,p_cap bigint)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE v bigint;
BEGIN
 INSERT INTO englishnotes_private.cloud_usage AS u VALUES(p_scope,p_bucket,p_amount)
 ON CONFLICT(scope,bucket) DO UPDATE SET amount=LEAST(u.amount+EXCLUDED.amount,9223372036854770000)
 RETURNING amount INTO v;
 RETURN v<=p_cap;
END $$;
CREATE FUNCTION englishnotes_private.gate(p_write boolean DEFAULT false)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE c englishnotes_private.cloud_limits%ROWTYPE; u uuid:=auth.uid();
 n timestamptz:=clock_timestamp(); ok boolean;
BEGIN
 IF u IS NULL THEN RETURN 'unauthorized'; END IF;
 SELECT * INTO c FROM englishnotes_private.cloud_limits WHERE id FOR UPDATE;
 IF NOT c.enabled OR NOT c.auth_hook_ready OR c.emergency_stop
    OR c.limited_until>n THEN RETURN 'cloud_paused'; END IF;
 IF c.maintenance_at IS NULL OR c.maintenance_at<n-interval '1 hour' THEN
   DELETE FROM englishnotes_private.cloud_usage WHERE bucket<n-interval '2 days';
   DELETE FROM englishnotes_private.note_receipts WHERE created_at<n-interval '7 days';
   UPDATE englishnotes_private.cloud_limits SET maintenance_at=n WHERE id;
 END IF;
 ok:=englishnotes_private.tick('requests',date_trunc('day',n),1,
                              c.requests_day::bigint*c.safety_percent/100);
 IF NOT ok THEN
   UPDATE englishnotes_private.cloud_limits SET limited_until=date_trunc('day',n)+interval '1 day' WHERE id;
   RETURN 'budget_exhausted';
 END IF;
 IF NOT englishnotes_private.tick('requests:'||u,date_trunc('minute',n),1,c.requests_user_minute)
 THEN RETURN 'rate_limited'; END IF;
 IF p_write AND NOT englishnotes_private.tick('writes-global',date_trunc('day',n),1,
    c.writes_day::bigint*c.safety_percent/100) THEN
   UPDATE englishnotes_private.cloud_limits SET limited_until=date_trunc('day',n)+interval '1 day' WHERE id;
   RETURN 'budget_exhausted';
 END IF;
 IF p_write AND NOT englishnotes_private.tick('writes:'||u,date_trunc('minute',n),1,c.writes_user_minute)
 THEN RETURN 'rate_limited'; END IF;
 RETURN 'ok';
END $$;

CREATE FUNCTION public.en_before_user_created(event jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE c englishnotes_private.cloud_limits%ROWTYPE; ip inet; h text;
 n timestamptz:=clock_timestamp(); ok boolean;
BEGIN
 SELECT * INTO c FROM englishnotes_private.cloud_limits WHERE id FOR UPDATE;
 IF NOT c.enabled OR NOT c.auth_hook_ready OR c.emergency_stop OR c.limited_until>n THEN
   RETURN jsonb_build_object('error',jsonb_build_object('http_code',429,'message','Cloud registration paused'));
 END IF;
 IF (SELECT count(*) FROM auth.users)>=c.accounts_total THEN
   RETURN jsonb_build_object('error',jsonb_build_object('http_code',429,'message','Account budget reached'));
 END IF;
 BEGIN ip:=(event->'metadata'->>'ip_address')::inet;
 EXCEPTION WHEN OTHERS THEN ip:=NULL; END;
 IF ip IS NULL THEN
   RETURN jsonb_build_object('error',jsonb_build_object('http_code',403,'message','Trusted signup metadata required'));
 END IF;
 IF octet_length(COALESCE(event->'user'->'user_metadata',event->'user'->'raw_user_meta_data','{}'::jsonb)::text)>1024
 THEN RETURN jsonb_build_object('error',jsonb_build_object('http_code',400,'message','Signup metadata too large')); END IF;
 h:=encode(extensions.digest(c.ip_pepper||convert_to(network(set_masklen(ip,
       CASE WHEN family(ip)=6 THEN 64 ELSE 32 END))::text,'UTF8'),'sha256'),'hex');
 ok:=englishnotes_private.tick('signups',date_trunc('day',n),1,c.signup_day);
 -- Stop before allocating a new IP bucket once the global budget is exhausted.
 IF NOT ok THEN RETURN jsonb_build_object('error',jsonb_build_object('http_code',429,'message','Registration limit reached')); END IF;
 ok:=englishnotes_private.tick('signup-ip:'||h,date_trunc('hour',n),1,c.signup_ip_hour);
 IF NOT ok THEN RETURN jsonb_build_object('error',jsonb_build_object('http_code',429,'message','Registration limit reached')); END IF;
 RETURN '{}'::jsonb;
END $$;

CREATE FUNCTION public.en_status() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE c englishnotes_private.cloud_limits%ROWTYPE; n timestamptz:=clock_timestamp();
BEGIN
 SELECT * INTO c FROM englishnotes_private.cloud_limits WHERE id FOR UPDATE;
 IF NOT c.enabled OR NOT c.auth_hook_ready OR c.emergency_stop OR c.limited_until>n THEN
   RETURN jsonb_build_object('protocol',2,'enabled',false);
 END IF;
 IF NOT englishnotes_private.tick('requests',date_trunc('day',n),1,
    c.requests_day::bigint*c.safety_percent/100)
 OR NOT englishnotes_private.tick('egress',date_trunc('day',n),2048,
    c.egress_day_bytes*c.safety_percent/100) THEN
   UPDATE englishnotes_private.cloud_limits SET limited_until=date_trunc('day',n)+interval '1 day' WHERE id;
   RETURN jsonb_build_object('protocol',2,'enabled',false);
 END IF;
 RETURN jsonb_build_object('protocol',2,'enabled',true);
END $$;

CREATE FUNCTION public.en_create_session(p_local_id uuid,p_title text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE g text; c englishnotes_private.cloud_limits%ROWTYPE; s public.lesson_sessions%ROWTYPE;
 code text; expiry timestamptz; u uuid:=auth.uid(); n timestamptz:=clock_timestamp();
BEGIN
 g:=englishnotes_private.gate(true); IF g<>'ok' THEN RETURN jsonb_build_object('outcome',g); END IF;
 IF p_local_id IS NULL OR p_title IS NULL OR char_length(btrim(p_title)) NOT BETWEEN 1 AND 200
 THEN RETURN jsonb_build_object('outcome','invalid_input'); END IF;
 SELECT * INTO c FROM englishnotes_private.cloud_limits WHERE id;
 SELECT * INTO s FROM public.lesson_sessions WHERE id=p_local_id FOR UPDATE;
 IF FOUND THEN
   IF s.created_by<>u THEN RETURN jsonb_build_object('outcome','forbidden'); END IF;
   -- Lost response recovery: regenerate only an unconsumed invite, without extending expiry.
   IF s.status='active' AND s.invitation_code_hash IS NOT NULL AND s.invitation_expires_at>n THEN
     code:=encode(extensions.gen_random_bytes(32),'hex');
     UPDATE public.lesson_sessions SET invitation_code_hash=extensions.digest(code,'sha256') WHERE id=s.id;
   END IF;
   RETURN jsonb_build_object('outcome','ok','session',to_jsonb(s)-'invitation_code_hash','invitation_code',code);
 END IF;
 IF (SELECT count(*) FROM public.lesson_sessions)>=c.sessions_total
    OR (SELECT count(*) FROM public.lesson_members WHERE user_id=u)>=c.sessions_user_total
    OR (SELECT count(*) FROM public.lesson_sessions s1 JOIN public.lesson_members m ON m.lesson_id=s1.id
        WHERE m.user_id=u AND s1.status='active')>=c.sessions_user_active
 THEN RETURN jsonb_build_object('outcome','session_limit'); END IF;
 IF NOT englishnotes_private.tick('sessions:'||u,date_trunc('day',n),1,c.sessions_user_day)
    OR NOT englishnotes_private.tick('sessions',date_trunc('day',n),1,c.sessions_day)
 THEN RETURN jsonb_build_object('outcome','session_limit'); END IF;
 code:=encode(extensions.gen_random_bytes(32),'hex'); expiry:=n+make_interval(mins=>c.invitation_minutes);
 INSERT INTO public.lesson_sessions(id,title,created_by,invitation_code_hash,invitation_expires_at)
 VALUES(p_local_id,btrim(p_title),u,extensions.digest(code,'sha256'),expiry) RETURNING * INTO s;
 INSERT INTO public.lesson_members(lesson_id,user_id,role) VALUES(s.id,u,'student');
 RETURN jsonb_build_object('outcome','ok','session',to_jsonb(s)-'invitation_code_hash','invitation_code',code);
END $$;

CREATE FUNCTION public.en_join_session(p_code text,p_operation_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE g text; j record; s public.lesson_sessions%ROWTYPE; c integer;
BEGIN
 g:=englishnotes_private.gate(true); IF g<>'ok' THEN RETURN jsonb_build_object('outcome',g); END IF;
 SELECT s1.* INTO s FROM public.lesson_sessions s1 JOIN englishnotes_private.join_receipts r
 ON r.lesson_id=s1.id WHERE r.user_id=auth.uid() AND r.operation_id=p_operation_id;
 IF FOUND AND englishnotes_private.is_lesson_member(s.id) THEN
   RETURN jsonb_build_object('outcome','ok','session',to_jsonb(s)-'invitation_code_hash');
 END IF;
 IF p_operation_id IS NULL THEN RETURN jsonb_build_object('outcome','invalid_input'); END IF;
 SELECT sessions_user_total INTO c FROM englishnotes_private.cloud_limits WHERE id;
 IF (SELECT count(*) FROM public.lesson_members WHERE user_id=auth.uid())>=c
 OR (SELECT count(*) FROM public.lesson_sessions s1 JOIN public.lesson_members m ON m.lesson_id=s1.id
     WHERE m.user_id=auth.uid() AND s1.status='active')>=
    (SELECT sessions_user_active FROM englishnotes_private.cloud_limits WHERE id)
 THEN RETURN jsonb_build_object('outcome','session_limit'); END IF;
 SELECT * INTO j FROM public.join_lesson_session(p_code);
 IF j.outcome<>'ok' THEN RETURN jsonb_build_object('outcome',j.outcome); END IF;
 SELECT * INTO s FROM public.lesson_sessions WHERE id=j.lesson_id;
 INSERT INTO englishnotes_private.join_receipts VALUES(auth.uid(),p_operation_id,s.id);
 RETURN jsonb_build_object('outcome','ok','session',to_jsonb(s)-'invitation_code_hash');
END $$;

CREATE FUNCTION englishnotes_private.meter_response(p_value jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE c englishnotes_private.cloud_limits%ROWTYPE;
BEGIN
 SELECT * INTO c FROM englishnotes_private.cloud_limits WHERE id;
 IF NOT englishnotes_private.tick('egress',date_trunc('day',clock_timestamp()),
    octet_length(p_value::text)*2+1024,c.egress_day_bytes*c.safety_percent/100) THEN
   UPDATE englishnotes_private.cloud_limits SET limited_until=date_trunc('day',clock_timestamp())+interval '1 day' WHERE id;
   RETURN jsonb_build_object('outcome','budget_exhausted');
 END IF;
 RETURN p_value;
END $$;

CREATE FUNCTION public.en_read(p_after bigint DEFAULT 0,p_limit integer DEFAULT 64) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE g text; result jsonb; page jsonb; cursor_value bigint; c englishnotes_private.cloud_limits%ROWTYPE;
BEGIN
 g:=englishnotes_private.gate(); IF g<>'ok' THEN RETURN jsonb_build_object('outcome',g); END IF;
 IF p_after IS NULL OR p_limit IS NULL OR p_after<0 OR p_limit NOT BETWEEN 1 AND 64
 THEN RETURN jsonb_build_object('outcome','invalid_input'); END IF;
 SELECT * INTO c FROM englishnotes_private.cloud_limits WHERE id;
 -- Bound page bytes as well as rows, including larger rows retained from v1.
 WITH candidates AS MATERIALIZED (
  SELECT n.* FROM public.lesson_notes n JOIN public.lesson_members m ON m.lesson_id=n.lesson_id
  WHERE m.user_id=auth.uid() AND n.sync_seq>p_after ORDER BY n.sync_seq LIMIT p_limit
 ), sizes AS (
  SELECT candidate_row.id,sum(octet_length(to_jsonb(candidate_row)::text))
    OVER(ORDER BY candidate_row.sync_seq) AS bytes,
   row_number() OVER(ORDER BY candidate_row.sync_seq) AS rn FROM candidates candidate_row
 )
 SELECT COALESCE(jsonb_agg(to_jsonb(n) ORDER BY n.sync_seq),'[]'),COALESCE(max(n.sync_seq),p_after)
 INTO page,cursor_value FROM candidates n JOIN sizes z USING(id)
 WHERE z.bytes<=4194304 OR z.rn=1;
 result:=jsonb_build_object('outcome','ok','notes',page,'cursor',cursor_value,
  'has_more',EXISTS(SELECT 1 FROM public.lesson_notes n JOIN public.lesson_members m ON m.lesson_id=n.lesson_id
    WHERE m.user_id=auth.uid() AND n.sync_seq>cursor_value),
  'sessions',COALESCE((SELECT jsonb_agg(to_jsonb(s)-'invitation_code_hash')
    FROM public.lesson_sessions s JOIN public.lesson_members m ON m.lesson_id=s.id
    WHERE m.user_id=auth.uid()),'[]'));
 IF NOT englishnotes_private.tick('egress',date_trunc('day',clock_timestamp()),
   2*octet_length(result::text)+1024,c.egress_day_bytes*c.safety_percent/100) THEN
   UPDATE englishnotes_private.cloud_limits SET limited_until=date_trunc('day',clock_timestamp())+interval '1 day' WHERE id;
   RETURN jsonb_build_object('outcome','budget_exhausted');
 END IF;
 RETURN result;
END $$;

CREATE FUNCTION public.en_write_note(p_operation_id uuid,p_note_id uuid,p_lesson_id uuid,
 p_base_revision bigint,p_title text,p_content text,p_position bigint,p_deleted boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE g text; old public.lesson_notes%ROWTYPE; result jsonb;
 c englishnotes_private.cloud_limits%ROWTYPE; total bigint;
BEGIN
 g:=englishnotes_private.gate(true); IF g<>'ok' THEN RETURN jsonb_build_object('outcome',g); END IF;
 IF NOT englishnotes_private.is_lesson_member(p_lesson_id)
 THEN RETURN jsonb_build_object('outcome','forbidden'); END IF;
 SELECT response INTO result FROM englishnotes_private.note_receipts
 WHERE user_id=auth.uid() AND operation_id=p_operation_id;
 IF FOUND THEN
   IF result->'note'->>'id'<>p_note_id::text OR result->'note'->>'lesson_id'<>p_lesson_id::text
   THEN RETURN jsonb_build_object('outcome','invalid_input'); END IF;
   RETURN englishnotes_private.meter_response(result);
 END IF;
 IF NOT englishnotes_private.can_edit_lesson(p_lesson_id)
 THEN RETURN jsonb_build_object('outcome','session_closed'); END IF;
 SELECT * INTO c FROM englishnotes_private.cloud_limits WHERE id;
 IF p_operation_id IS NULL OR p_note_id IS NULL OR p_title IS NULL OR p_content IS NULL
 OR p_deleted IS NULL OR p_position IS NULL OR p_position<0 OR p_base_revision IS NULL OR p_base_revision<0
 OR char_length(p_title)>200 OR octet_length(p_title)+octet_length(p_content)>c.note_bytes
 THEN RETURN jsonb_build_object('outcome','note_too_large_or_invalid'); END IF;
 SELECT * INTO old FROM public.lesson_notes WHERE id=p_note_id FOR UPDATE;
 IF FOUND AND old.lesson_id<>p_lesson_id THEN RETURN jsonb_build_object('outcome','forbidden'); END IF;
 IF (old.id IS NULL AND p_base_revision<>0) OR (old.id IS NOT NULL AND old.revision<>p_base_revision)
 THEN RETURN englishnotes_private.meter_response(jsonb_build_object('outcome','conflict','note',CASE WHEN old.id IS NULL THEN NULL ELSE to_jsonb(old) END)); END IF;
 IF old.id IS NULL AND (SELECT count(*) FROM public.lesson_notes WHERE lesson_id=p_lesson_id)>=c.notes_session
 THEN RETURN jsonb_build_object('outcome','note_limit'); END IF;
 SELECT COALESCE(sum(octet_length(content)+octet_length(title)+512),0) INTO total FROM public.lesson_notes;
 total:=total+(SELECT COALESCE(sum(pg_column_size(response)+128),0) FROM englishnotes_private.note_receipts)
  +(SELECT count(*)*1024 FROM public.lesson_sessions)+(SELECT count(*)*256 FROM public.lesson_members)
  +(SELECT count(*)*2048 FROM auth.users);
 total:=total+octet_length(p_content)+octet_length(p_title)+512-
  CASE WHEN old.id IS NULL THEN 0 ELSE octet_length(old.content)+octet_length(old.title)+512 END;
 IF total+octet_length(p_content)+octet_length(p_title)+2048>c.stored_bytes*c.safety_percent/100
 THEN RETURN jsonb_build_object('outcome','storage_budget_exhausted'); END IF;
 IF old.id IS NULL THEN
  INSERT INTO public.lesson_notes(id,lesson_id,author_id,title,content,position,deleted_at)
  VALUES(p_note_id,p_lesson_id,auth.uid(),p_title,p_content,p_position,
         CASE WHEN p_deleted THEN clock_timestamp() ELSE NULL END) RETURNING * INTO old;
 ELSE
  UPDATE public.lesson_notes SET title=p_title,content=p_content,position=p_position,
   deleted_at=CASE WHEN p_deleted THEN clock_timestamp() ELSE NULL END WHERE id=p_note_id RETURNING * INTO old;
 END IF;
 result:=jsonb_build_object('outcome','ok','note',to_jsonb(old));
 INSERT INTO englishnotes_private.note_receipts(user_id,operation_id,response) VALUES(auth.uid(),p_operation_id,result);
 -- Bounded receipt retention; old retries still cannot overwrite a newer revision.
 DELETE FROM englishnotes_private.note_receipts WHERE created_at<clock_timestamp()-interval '7 days';
 RETURN englishnotes_private.meter_response(result);
END $$;

CREATE FUNCTION public.en_finish_session(p_lesson_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE g text;
BEGIN
 g:=englishnotes_private.gate(true); IF g<>'ok' THEN RETURN jsonb_build_object('outcome',g); END IF;
 IF NOT EXISTS(SELECT 1 FROM public.lesson_sessions WHERE id=p_lesson_id AND created_by=auth.uid())
 THEN RETURN jsonb_build_object('outcome','forbidden'); END IF;
 UPDATE public.lesson_sessions SET status='closed',invitation_code_hash=NULL,invitation_expires_at=NULL
 WHERE id=p_lesson_id;
 RETURN jsonb_build_object('outcome','ok');
END $$;

-- Private invalidation broadcast: never send note text/authors over unmetered broadcasts.
CREATE FUNCTION englishnotes_private.notify_session() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE v_id uuid;
BEGIN
 IF TG_TABLE_NAME='lesson_notes' THEN v_id:=NEW.lesson_id; ELSE v_id:=NEW.id; END IF;
 BEGIN
   PERFORM realtime.send(jsonb_build_object('changed',true),'changed','lesson:'||v_id,true);
 EXCEPTION WHEN OTHERS THEN
   -- Broadcast is a hint. A realtime outage must not roll back a committed note.
   NULL;
 END;
 RETURN NEW;
END $$;
CREATE TRIGGER notify_notes AFTER INSERT OR UPDATE ON public.lesson_notes
 FOR EACH ROW EXECUTE FUNCTION englishnotes_private.notify_session();
CREATE TRIGGER notify_session AFTER UPDATE ON public.lesson_sessions
 FOR EACH ROW EXECUTE FUNCTION englishnotes_private.notify_session();
CREATE FUNCTION englishnotes_private.receive_topic() RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path='' AS $$
DECLARE lesson uuid; c englishnotes_private.cloud_limits%ROWTYPE;
BEGIN
 SELECT * INTO c FROM englishnotes_private.cloud_limits WHERE id;
 IF NOT c.enabled OR c.emergency_stop OR c.limited_until>clock_timestamp() THEN RETURN false; END IF;
 BEGIN lesson:=substring(realtime.topic() FROM 8)::uuid;
 EXCEPTION WHEN OTHERS THEN RETURN false; END;
 RETURN realtime.topic()='lesson:'||lesson::text AND englishnotes_private.is_lesson_member(lesson);
END $$;
CREATE POLICY englishnotes_receive ON realtime.messages FOR SELECT TO authenticated
 USING (extension='broadcast' AND topic=realtime.topic() AND englishnotes_private.receive_topic());
CREATE POLICY englishnotes_receive_guard ON realtime.messages AS RESTRICTIVE FOR SELECT TO authenticated
 USING (extension='broadcast' AND topic=realtime.topic() AND englishnotes_private.receive_topic());
CREATE POLICY englishnotes_no_client_broadcast ON realtime.messages AS RESTRICTIVE
 FOR INSERT TO authenticated WITH CHECK(false);

-- Retain data/RLS, but revoke v1 bypasses. Only v2 bounded POST RPCs access user data.
REVOKE ALL ON public.lesson_sessions,public.lesson_members,public.lesson_notes FROM PUBLIC,authenticated,anon;
-- Table-level REVOKE does not revoke column grants.
REVOKE SELECT(id,title,created_by,created_at,invitation_expires_at,status) ON public.lesson_sessions FROM authenticated;
REVOKE INSERT(id,lesson_id,author_id,title,content,position) ON public.lesson_notes FROM authenticated;
REVOKE UPDATE(title,content,position,deleted_at) ON public.lesson_notes FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.create_lesson_session(text,text,interval),public.join_lesson_session(text)
 FROM authenticated,anon,PUBLIC;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_publication_tables WHERE pubname='supabase_realtime' AND schemaname='public'
 AND tablename='lesson_notes') THEN ALTER PUBLICATION supabase_realtime DROP TABLE public.lesson_notes; END IF;
END $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA englishnotes_private FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION englishnotes_private.receive_topic() TO authenticated;
REVOKE ALL ON FUNCTION public.en_status(),public.en_create_session(uuid,text),public.en_join_session(text,uuid),
 public.en_read(bigint,integer),public.en_write_note(uuid,uuid,uuid,bigint,text,text,bigint,boolean),
 public.en_finish_session(uuid),public.en_before_user_created(jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.en_status() TO anon,authenticated;
GRANT EXECUTE ON FUNCTION public.en_create_session(uuid,text),public.en_join_session(text,uuid),
 public.en_read(bigint,integer),public.en_write_note(uuid,uuid,uuid,bigint,text,text,bigint,boolean),
 public.en_finish_session(uuid) TO authenticated;
GRANT USAGE ON SCHEMA public TO supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.en_before_user_created(jsonb) TO supabase_auth_admin;
COMMIT;
