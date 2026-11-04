CREATE TABLE IF NOT EXISTS public.telegram_menu_buttons (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    label text NOT NULL UNIQUE,
    reply_text text NOT NULL,
    updated_at timestamptz NOT NULL,
    update_id bigint NOT NULL
);

ALTER TABLE public.telegram_menu_buttons
    ADD COLUMN IF NOT EXISTS source_chat_id bigint,
    ADD COLUMN IF NOT EXISTS source_started_message_id bigint,
    ADD COLUMN IF NOT EXISTS source_done_message_id bigint,
    ADD COLUMN IF NOT EXISTS message_ids bigint[] NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS public.telegram_menu_drafts (
    chat_id bigint PRIMARY KEY,
    label text NOT NULL,
    started_message_id bigint NOT NULL,
    done_message_id bigint,
    message_ids bigint[] NOT NULL DEFAULT '{}'
);
