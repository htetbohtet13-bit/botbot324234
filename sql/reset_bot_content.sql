-- Run once when moving to a different Telegram bot and rebuilding its content.
-- Keep subscriber records, button labels, and button replies saved as plain text.
BEGIN;

UPDATE public.telegram_welcome
SET draft_started = 0,
    editing = false,
    draft_ids = '{}',
    published_from = 0,
    published_to = 0,
    published_ids = '{}'
WHERE owner_id = 5168675744;

DELETE FROM public.telegram_menu_drafts;

UPDATE public.telegram_menu_buttons
SET source_chat_id = NULL,
    source_started_message_id = NULL,
    source_done_message_id = NULL,
    message_ids = '{}';

COMMIT;
