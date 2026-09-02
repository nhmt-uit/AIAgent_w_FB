---
skill: Content Context Awareness
used_by: [content-strategist]
---

> **Purpose of this file / Mục đích của file này:**
>
> EN: Rules for grounding generated posts/comments in real context instead of generic filler — read this when content looks repetitive, generic, or unrelated to the target post.
> VI: Quy tắc bắt buộc nội dung do agent soạn phải bám sát ngữ cảnh thật, không viết chung chung — đọc file này khi thấy nội dung lặp lại, sáo rỗng, hoặc không liên quan bài viết gốc.

# Skill: Content Context Awareness

## Why

Generic, repetitive content is the clearest content-level bot signal
(e.g. the same "Great post! 👍" appearing under unrelated posts). This
skill governs how the Content Strategist Agent must ground its drafts in
real context before writing anything.

## Required context before drafting a comment or reply

1. The target post's own content (fetched via the `read_recent_comments` /
   page-read action in `skills/facebook-custom-actions.md`, which also
   returns the post body).
2. The most recent comments already on that post, to avoid duplicating
   what's already been said and to reference the actual conversation.
3. This account's own last N (default 5) posts/comments, to avoid
   repeating phrasing.

## Drafting rules

- The draft must reference something specific from the target (a phrase,
  claim, question, or detail in the post) — never a template that could
  apply to any post.
- If the target content is too thin to say anything specific and relevant
  about, the Content Strategist should prefer a `like` action over forcing
  a generic comment, or return `action: null` with reasoning.
- Keep a rolling local log (per account) of the last N generated
  posts/comments so the "don't repeat yourself" check in
  `docs/agents/content-strategist.md` has something to check against.

## Relationship to brand voice

Tone/vocabulary/banned topics come from the project's brand-voice
reference (to be added under `docs/`) — this skill is about *what to react
to and how to ground it*, not tone itself.
