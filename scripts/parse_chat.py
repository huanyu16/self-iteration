#!/usr/bin/env python3
"""
Self-Iteration Chat Parser
解析多种聊天记录格式，输出标准化 JSON。
支持：微信、Telegram、WhatsApp、Discord、通用文本
"""

import json
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime


def detect_format(file_path: str, content: str) -> str:
    """自动检测聊天记录格式"""
    path = Path(file_path)
    ext = path.suffix.lower()
    first_500 = content[:500]

    # JSON formats
    if ext == ".json":
        try:
            data = json.loads(content)
            if "messages" in data:
                first_msg = data["messages"][0] if data["messages"] else {}
                # WeFlow (WeChat backup tool): has "weflow" key or isSend/formattedTime fields
                if "weflow" in data or ("isSend" in first_msg and "formattedTime" in first_msg):
                    return "weflow"
                if "text_entities" in first_msg or "from" in first_msg:
                    return "telegram"
                if "author" in first_msg:
                    return "discord"
        except json.JSONDecodeError:
            pass

    # WhatsApp: [DD/MM/YYYY, HH:MM:SS] or [MM/DD/YYYY, HH:MM:SS]
    if re.search(r'\[\d{1,2}/\d{1,2}/\d{2,4},\s\d{1,2}:\d{2}:\d{2}\]', first_500):
        return "whatsapp"

    # WeChat CSV: CreateTime,NickName,StrContent
    if "CreateTime,NickName,StrContent" in first_500 or "NickName,StrContent" in first_500:
        return "wechat_csv"

    # WeChat TXT: YYYY/MM/DD HH:MM:SS followed by name on next line
    if re.search(r'\d{4}/\d{1,2}/\d{1,2}\s\d{1,2}:\d{2}:\d{2}', first_500):
        return "wechat_txt"

    # HTML
    if ext == ".html" or ext == ".htm":
        return "html"

    return "generic"


def parse_wechat_txt(content: str) -> list:
    """解析微信 TXT 导出格式"""
    messages = []
    # Pattern: date time name\ncontent\n
    pattern = re.compile(
        r'(\d{4}/\d{1,2}/\d{1,2}\s\d{1,2}:\d{2}:\d{2})\s+(.+?)\n(.*?)(?=\n\d{4}/\d{1,2}/\d{1,2}\s|\Z)',
        re.DOTALL
    )
    for match in pattern.finditer(content):
        timestamp_str, sender, text = match.groups()
        text = text.strip()
        if not text:
            continue
        msg_type = classify_message(text)
        messages.append({
            "timestamp": normalize_timestamp(timestamp_str),
            "sender": sender.strip(),
            "content": text,
            "type": msg_type
        })
    return messages


def parse_wechat_csv(content: str) -> list:
    """解析微信 CSV 导出格式"""
    messages = []
    lines = content.strip().split('\n')
    if not lines:
        return messages

    # Skip header
    start = 1 if 'CreateTime' in lines[0] or 'NickName' in lines[0] else 0

    for line in lines[start:]:
        # Handle CSV with potential commas in content
        parts = line.split(',', 2)
        if len(parts) < 3:
            continue
        timestamp_str, sender, text = parts[0].strip(), parts[1].strip(), parts[2].strip()
        # Remove surrounding quotes if present
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        if not text:
            continue
        messages.append({
            "timestamp": normalize_timestamp(timestamp_str),
            "sender": sender,
            "content": text,
            "type": classify_message(text)
        })
    return messages


def parse_telegram(content: str) -> list:
    """解析 Telegram JSON 导出格式"""
    messages = []
    data = json.loads(content)

    for msg in data.get("messages", []):
        # Extract text
        text = msg.get("text", "")
        if isinstance(text, list):
            # Rich text: extract plain text parts
            text = "".join(
                part if isinstance(part, str) else part.get("text", "")
                for part in text
            )
        if not text:
            continue

        sender = msg.get("from", "") or msg.get("actor", "") or "System"
        timestamp_str = msg.get("date", "")

        messages.append({
            "timestamp": normalize_timestamp(timestamp_str),
            "sender": sender,
            "content": text.strip(),
            "type": classify_message(text)
        })
    return messages


def parse_whatsapp(content: str) -> list:
    """解析 WhatsApp 导出格式"""
    messages = []
    # Pattern: [DD/MM/YYYY, HH:MM:SS] Sender: Message
    pattern = re.compile(
        r'\[(\d{1,2}/\d{1,2}/\d{2,4}),\s(\d{1,2}:\d{2}:\d{2})\]\s(.+?):\s(.*?)(?=\n\[\d{1,2}/\d{1,2}|\Z)',
        re.DOTALL
    )
    for match in pattern.finditer(content):
        date_str, time_str, sender, text = match.groups()
        text = text.strip()
        if not text:
            continue
        timestamp_str = f"{date_str} {time_str}"
        messages.append({
            "timestamp": normalize_timestamp(timestamp_str),
            "sender": sender.strip(),
            "content": text,
            "type": classify_message(text)
        })
    return messages


def parse_discord(content: str) -> list:
    """解析 Discord JSON 导出格式"""
    messages = []
    data = json.loads(content)

    for msg in data.get("messages", []):
        text = msg.get("content", "")
        if not text:
            continue

        author = msg.get("author", {})
        sender = author.get("nickname") or author.get("name", "Unknown")
        timestamp_str = msg.get("timestamp", "")

        messages.append({
            "timestamp": normalize_timestamp(timestamp_str),
            "sender": sender,
            "content": text.strip(),
            "type": classify_message(text)
        })
    return messages


def parse_generic(content: str) -> list:
    """通用解析：尝试识别时间戳+发送者+内容的模式"""
    messages = []

    # Try common patterns
    patterns = [
        # YYYY-MM-DD HH:MM:SS Sender: Content
        re.compile(r'(\d{4}-\d{1,2}-\d{1,2}\s\d{1,2}:\d{2}(?::\d{2})?)\s+(.+?)[：:]\s*(.*?)(?=\n\d{4}-\d{1,2}|\Z)', re.DOTALL),
        # MM/DD HH:MM Sender: Content
        re.compile(r'(\d{1,2}/\d{1,2}\s\d{1,2}:\d{2})\s+(.+?)[：:]\s*(.*?)(?=\n\d{1,2}/\d{1,2}|\Z)', re.DOTALL),
        # HH:MM:SS Sender: Content
        re.compile(r'(\d{1,2}:\d{2}:\d{2})\s+(.+?)[：:]\s*(.*?)(?=\n\d{1,2}:\d{2}|\Z)', re.DOTALL),
    ]

    for pattern in patterns:
        matches = list(pattern.finditer(content))
        if len(matches) > 5:  # At least 5 matches to be confident
            for match in matches:
                timestamp_str, sender, text = match.groups()
                text = text.strip()
                if text:
                    messages.append({
                        "timestamp": normalize_timestamp(timestamp_str),
                        "sender": sender.strip(),
                        "content": text,
                        "type": classify_message(text)
                    })
            break

    # If no pattern matched, split by lines and treat each as a message
    if not messages:
        for i, line in enumerate(content.strip().split('\n')):
            line = line.strip()
            if line:
                messages.append({
                    "timestamp": None,
                    "sender": "unknown",
                    "content": line,
                    "type": classify_message(line)
                })

    return messages


def classify_message(text: str) -> str:
    """分类消息类型"""
    media_markers = ['[图片]', '[视频]', '[语音]', '[文件]', '[位置]',
                     '[Photo]', '[Video]', '[Audio]', '[Document]', '[Sticker]',
                     '<Media omitted>', '<图片>', '<视频>']
    for marker in media_markers:
        if marker in text:
            return "media"

    system_markers = ['撤回了一条消息', '加入了群聊', '退出了群聊',
                      '修改群名为', '你已添加了', '邀请', 'joined', 'left',
                      'changed the group', 'Messages to this']
    for marker in system_markers:
        if marker in text:
            return "system"

    if len(text) <= 3 and any(c in text for c in '😀😃😄😁😆😅🤣😂🙂😊😍🥰😘😗😙😚'):
        return "sticker"

    return "text"


def parse_weflow(content: str) -> list:
    """解析 WeFlow 微信备份导出格式"""
    messages = []
    data = json.loads(content)

    # Map Chinese type names to our standard types
    type_map = {
        "文本消息": "text",
        "图片消息": "media",
        "视频消息": "media",
        "语音消息": "media",
        "动画表情": "sticker",
        "系统消息": "system",
        "引用消息": "text",
        "位置消息": "media",
        "通话消息": "system",
        "其他消息": "system",
    }

    for msg in data.get("messages", []):
        content_text = msg.get("content", "")
        if not content_text:
            continue

        msg_type_raw = msg.get("type", "其他消息")
        msg_type = type_map.get(msg_type_raw, "text")

        # isSend: 1 = user sent, 0 = other sent
        is_send = msg.get("isSend", 0)
        sender = "self" if is_send == 1 else msg.get("senderDisplayName", "unknown")

        # Timestamp: use formattedTime directly (already ISO-like)
        timestamp = msg.get("formattedTime", "")
        if timestamp:
            # Convert "2026-03-15 11:37:21" to ISO
            try:
                dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                timestamp = dt.isoformat()
            except ValueError:
                pass

        # For 引用消息, the content may contain the quoted text — just use as-is
        messages.append({
            "timestamp": timestamp,
            "sender": sender,
            "content": content_text.strip(),
            "type": msg_type,
        })

    return messages


def normalize_timestamp(ts: str) -> str:
    """标准化时间戳格式为 ISO 8601"""
    if not ts:
        return ""

    formats = [
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%d/%m/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M",
        "%m/%d/%Y %H:%M",
        "%H:%M:%S",
        "%H:%M",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(ts.strip(), fmt)
            return dt.isoformat()
        except ValueError:
            continue

    return ts  # Return as-is if no format matches


def compute_metadata(messages: list, source: str) -> dict:
    """计算元数据"""
    if not messages:
        return {}

    senders = list(set(m["sender"] for m in messages if m["sender"] not in ("System", "self")))
    # Identify user (self) messages count
    self_count = len([m for m in messages if m["sender"] == "self" and m["type"] == "text"])
    timestamps = [m["timestamp"] for m in messages if m["timestamp"]]

    return {
        "source": source,
        "total_messages": len(messages),
        "text_messages": len([m for m in messages if m["type"] == "text"]),
        "media_messages": len([m for m in messages if m["type"] == "media"]),
        "system_messages": len([m for m in messages if m["type"] == "system"]),
        "self_messages": self_count,
        "date_range": {
            "start": min(timestamps) if timestamps else "",
            "end": max(timestamps) if timestamps else ""
        },
        "participants": sorted(senders),
        "message_count_by_sender": {
            sender: len([m for m in messages if m["sender"] == sender and m["type"] == "text"])
            for sender in senders + (["self"] if self_count > 0 else [])
        }
    }


def parse(file_path: str, fmt: str = "auto") -> dict:
    """主解析函数"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Read file with encoding detection
    content = None
    for encoding in ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin-1']:
        try:
            content = path.read_text(encoding=encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if content is None:
        raise ValueError(f"Cannot decode file: {file_path}")

    # Detect format
    if fmt == "auto":
        fmt = detect_format(file_path, content)

    # Parse
    parsers = {
        "wechat_txt": parse_wechat_txt,
        "wechat_csv": parse_wechat_csv,
        "wechat": parse_wechat_txt,
        "weflow": parse_weflow,
        "telegram": parse_telegram,
        "whatsapp": parse_whatsapp,
        "discord": parse_discord,
        "generic": parse_generic,
    }

    parser = parsers.get(fmt, parse_generic)
    messages = parser(content)

    # Filter out empty messages
    messages = [m for m in messages if m.get("content", "").strip()]

    result = {
        "metadata": compute_metadata(messages, fmt),
        "messages": messages
    }

    return result


def main():
    arg_parser = argparse.ArgumentParser(description="Parse chat records into standardized JSON")
    arg_parser.add_argument("file", help="Path to chat record file")
    arg_parser.add_argument("--format", "-f", default="auto",
                           choices=["auto", "wechat", "wechat_txt", "wechat_csv",
                                   "telegram", "whatsapp", "discord", "generic"],
                           help="Chat format (default: auto-detect)")
    arg_parser.add_argument("--output", "-o", default="stdout",
                           help="Output file path (default: stdout)")
    arg_parser.add_argument("--stats-only", action="store_true",
                           help="Only output metadata/stats, skip messages")

    args = arg_parser.parse_args()

    try:
        result = parse(args.file, args.format)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.stats_only:
        output = json.dumps(result["metadata"], ensure_ascii=False, indent=2)
    else:
        output = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output == "stdout":
        print(output)
    else:
        Path(args.output).write_text(output, encoding='utf-8')
        print(f"Output written to: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
