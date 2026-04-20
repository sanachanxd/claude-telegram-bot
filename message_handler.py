import re
from telegram import Update
from telegram.constants import ParseMode, ChatAction

MAX_MSG_LEN = 4000

def smart_split(text: str) -> list[str]:
    if len(text) <= MAX_MSG_LEN:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= MAX_MSG_LEN:
            chunks.append(remaining)
            break

        split_at = MAX_MSG_LEN
        code_fence = remaining.rfind("\n```\n", 0, split_at)
        if code_fence > MAX_MSG_LEN // 2:
            split_at = code_fence + 4
        else:
            para = remaining.rfind("\n\n", 0, split_at)
            if para > MAX_MSG_LEN // 2:
                split_at = para + 1
            else:
                line = remaining.rfind("\n", 0, split_at)
                if line > MAX_MSG_LEN // 2:
                    split_at = line + 1

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]

    return chunks

def escape_markdown_v2(text: str) -> str:
    return text

async def send_thinking(update: Update):
    msg = await update.message.reply_text(
        "thinking...",
        parse_mode=None,
    )
    await update.message.chat.send_action(ChatAction.TYPING)
    return msg

async def send_response(update: Update, text: str, thinking_msg=None):
    if thinking_msg:
        try:
            await thinking_msg.delete()
        except Exception:
            pass

    chunks = smart_split(text)
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(chunk, parse_mode=None)

async def send_error(update: Update, error: str, thinking_msg=None):
    if thinking_msg:
        try:
            await thinking_msg.delete()
        except Exception:
            pass
    await update.message.reply_text(f"Error: {error}")
