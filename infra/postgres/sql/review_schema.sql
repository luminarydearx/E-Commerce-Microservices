-- Review Service schema
CREATE SCHEMA IF NOT EXISTS review;

CREATE TABLE IF NOT EXISTS review.reviews (
    id UUID PRIMARY KEY,
    product_id UUID NOT NULL,
    order_item_id UUID NOT NULL,
    user_id UUID NOT NULL,
    seller_id UUID NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL CHECK (length(content) <= 5000),
    images JSONB,
    is_anonymous BOOLEAN NOT NULL DEFAULT FALSE,
    is_edited BOOLEAN NOT NULL DEFAULT FALSE,
    is_hidden BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    helpful_count INTEGER NOT NULL DEFAULT 0,
    not_helpful_count INTEGER NOT NULL DEFAULT 0,
    seller_response TEXT,
    seller_response_at TIMESTAMPTZ,
    moderation_status VARCHAR(20) NOT NULL DEFAULT 'APPROVED',
    moderation_reason VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT chk_moderation_status CHECK (moderation_status IN ('APPROVED', 'PENDING', 'HIDDEN', 'REJECTED')),
    CONSTRAINT uq_user_product_review UNIQUE (user_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_reviews_product ON review.reviews(product_id, is_deleted, is_hidden);
CREATE INDEX IF NOT EXISTS idx_reviews_user ON review.reviews(user_id, is_deleted);
CREATE INDEX IF NOT EXISTS idx_reviews_seller ON review.reviews(seller_id);
CREATE INDEX IF NOT EXISTS idx_reviews_rating ON review.reviews(product_id, rating);
CREATE INDEX IF NOT EXISTS idx_reviews_helpful ON review.reviews(product_id, helpful_count DESC);
CREATE INDEX IF NOT EXISTS idx_reviews_created ON review.reviews(created_at DESC);

CREATE TABLE IF NOT EXISTS review.helpful_votes (
    id UUID PRIMARY KEY,
    review_id UUID NOT NULL REFERENCES review.reviews(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    helpful BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_helpful_review_user UNIQUE (review_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_helpful_user ON review.helpful_votes(user_id);

-- Function to update helpful_count on review when vote is added
CREATE OR REPLACE FUNCTION review.update_helpful_count() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.helpful THEN
        UPDATE review.reviews SET helpful_count = helpful_count + 1 WHERE id = NEW.review_id;
    ELSE
        UPDATE review.reviews SET not_helpful_count = not_helpful_count + 1 WHERE id = NEW.review_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION review.decrement_helpful_count() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.helpful THEN
        UPDATE review.reviews SET helpful_count = GREATEST(0, helpful_count - 1) WHERE id = OLD.review_id;
    ELSE
        UPDATE review.reviews SET not_helpful_count = GREATEST(0, not_helpful_count - 1) WHERE id = OLD.review_id;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_helpful_insert ON review.helpful_votes;
CREATE TRIGGER trg_helpful_insert AFTER INSERT ON review.helpful_votes
    FOR EACH ROW EXECUTE FUNCTION review.update_helpful_count();

DROP TRIGGER IF EXISTS trg_helpful_delete ON review.helpful_votes;
CREATE TRIGGER trg_helpful_delete AFTER DELETE ON review.helpful_votes
    FOR EACH ROW EXECUTE FUNCTION review.decrement_helpful_count();

-- Materialized view for product rating summary (refresh periodically)
CREATE MATERIALIZED VIEW IF NOT EXISTS review.product_rating_summary AS
SELECT
    product_id,
    AVG(rating)::numeric(3,2) AS average_rating,
    COUNT(*) AS total_reviews,
    COUNT(*) FILTER (WHERE rating = 5) AS rating_5,
    COUNT(*) FILTER (WHERE rating = 4) AS rating_4,
    COUNT(*) FILTER (WHERE rating = 3) AS rating_3,
    COUNT(*) FILTER (WHERE rating = 2) AS rating_2,
    COUNT(*) FILTER (WHERE rating = 1) AS rating_1
FROM review.reviews
WHERE is_deleted = FALSE AND is_hidden = FALSE AND moderation_status = 'APPROVED'
GROUP BY product_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_product_rating_summary ON review.product_rating_summary(product_id);
