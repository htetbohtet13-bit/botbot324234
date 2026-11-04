CREATE TABLE IF NOT EXISTS public.telegram_subscribers (
    chat_id bigint PRIMARY KEY,
    first_started_at timestamptz NOT NULL,
    last_started_at timestamptz NOT NULL
);
