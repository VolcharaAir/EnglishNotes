-- Isolated PostgreSQL fixture only. Never execute in Supabase Dashboard.
CREATE ROLE supabase_auth_admin NOLOGIN;
CREATE SCHEMA realtime;
CREATE TABLE realtime.messages(extension text, topic text, payload jsonb, private boolean);
ALTER TABLE realtime.messages ENABLE ROW LEVEL SECURITY;
GRANT USAGE ON SCHEMA realtime TO authenticated;
GRANT SELECT ON realtime.messages TO authenticated;
CREATE FUNCTION realtime.topic() RETURNS text LANGUAGE sql STABLE AS $$
 SELECT current_setting('test.realtime_topic',true)
$$;
CREATE FUNCTION realtime.send(payload jsonb,event text,topic text,private boolean) RETURNS void
LANGUAGE sql AS $$ INSERT INTO realtime.messages VALUES('broadcast',topic,payload,private) $$;
