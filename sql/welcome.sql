CREATE TABLE IF NOT EXISTS public.telegram_welcome (
    owner_id bigint PRIMARY KEY,
    draft_started bigint NOT NULL DEFAULT 0,
    editing boolean NOT NULL DEFAULT false,
    draft_ids bigint[] NOT NULL DEFAULT '{}',
    published_from bigint NOT NULL DEFAULT 0,
    published_to bigint NOT NULL DEFAULT 0,
    published_ids bigint[] NOT NULL DEFAULT '{}'
);
