-- Migration 0016: Add indexes to support fast tagged-user document access lookup.
-- When a user is @mentioned in a comment, we check comment_mentions to grant
-- them limited (read + comment) access to the document. These indexes make
-- that check efficient.

-- Fast lookup: "was user X mentioned in any comment?"
CREATE INDEX IF NOT EXISTS idx_comment_mentions_mentioned_user
    ON comment_mentions (mentioned_user_id);

-- Fast lookup: "get all comments for review Y"
CREATE INDEX IF NOT EXISTS idx_content_comments_review_id
    ON content_comments (review_id);
