CREATE SCHEMA IF NOT EXISTS chat;

CREATE TABLE IF NOT EXISTS chat.conversations (
    id UUID PRIMARY KEY,
    buyer_id UUID NOT NULL,
    seller_id UUID NOT NULL,
    product_id UUID,
    last_message_at TIMESTAMPTZ,
    last_message_preview TEXT,
    buyer_unread INTEGER NOT NULL DEFAULT 0,
    seller_unread INTEGER NOT NULL DEFAULT 0,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_no_self_chat CHECK (buyer_id != seller_id)
);
CREATE INDEX IF NOT EXISTS idx_conversations_buyer ON chat.conversations(buyer_id, is_deleted);
CREATE INDEX IF NOT EXISTS idx_conversations_seller ON chat.conversations(seller_id, is_deleted);
CREATE INDEX IF NOT EXISTS idx_conversations_product ON chat.conversations(product_id);

CREATE TABLE IF NOT EXISTS chat.messages (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES chat.conversations(id) ON DELETE CASCADE,
    sender_id UUID NOT NULL,
    sender_role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    type VARCHAR(20) NOT NULL DEFAULT 'text',
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON chat.messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON chat.messages(sender_id);
