# 聊天记录格式解析指南

## 格式自动检测

按以下顺序检测文件格式：

1. 文件扩展名：`.json` → 尝试 Telegram/Discord 格式；`.txt`/`.csv` → 尝试微信/WhatsApp/通用格式
2. 文件首行内容特征匹配
3. 都无法匹配时，按通用文本格式处理

---

## 微信导出格式

### 特征
- 通常为 `.txt` 或 `.csv` 文件
- 每条消息格式：`日期 时间 昵称\n消息内容\n`
- 或 CSV 格式：`时间,NickName,StrContent`

### 解析规则
```
模式1（TXT）：
{YYYY}/{MM}/{DD} {HH}:{MM}:{SS} {昵称}
{消息内容}
（空行分隔）

模式2（CSV）：
CreateTime,NickName,StrContent
2024/01/15 14:30:22,张三,你好啊
```

### 注意
- 微信导出可能包含系统消息（"xxx 撤回了一条消息"、"xxx 加入群聊"）——标记为 `type: system`
- 图片/视频/文件消息通常显示为 `[图片]` `[视频]` `[文件]`——标记为 `type: media`
- 引用/回复消息可能有特殊格式

---

## Telegram 导出格式

### 特征
- JSON 格式，文件名通常为 `result.json`
- 顶层结构：`{ "messages": [...] }`

### 解析规则
```json
{
  "messages": [
    {
      "id": 123,
      "date": "2024-01-15T14:30:22",
      "from": "张三",
      "text": "消息内容",
      "text_entities": [...]
    }
  ]
}
```

- `text` 可能是字符串或数组（富文本格式，含实体）
- 数组时提取所有 `type: "plain"` 的文本拼接
- `from` 为空表示系统消息

---

## WhatsApp 导出格式

### 特征
- `.txt` 文件，包含聊天导出
- 格式：`[DD/MM/YYYY, HH:MM:SS] 发送者: 消息内容`

### 解析规则
```
[15/01/2024, 14:30:22] 张三: 你好啊
[15/01/2024, 14:30:45] 李四: 你好
```

### 注意
- 日期格式可能因系统语言而异
- 多行消息只有第一行有时间戳前缀
- 加密消息导出可能显示为不可读

---

## Discord 导出格式

### 特征
- JSON 格式（由 DiscordChatExporter 等工具导出）
- 包含 channel、guild 等元信息

### 解析规则
```json
{
  "messages": [
    {
      "timestamp": "2024-01-15T14:30:22.123Z",
      "author": { "name": "张三", "nickname": "..." },
      "content": "消息内容"
    }
  ]
}
```

---

## 通用文本格式

当无法匹配上述格式时，使用通用解析策略：

1. 尝试识别每行的"时间戳 + 发送者 + 内容"模式
2. 时间戳格式：`YYYY-MM-DD HH:MM` 或 `MM/DD HH:MM` 等
3. 发送者：时间戳后、冒号前的文本
4. 如果完全无法识别结构，将整个文件作为纯文本分析

---

## 标准化输出格式

所有格式解析后统一为：

```json
{
  "metadata": {
    "source": "wechat|telegram|whatsapp|discord|generic",
    "total_messages": 1234,
    "date_range": { "start": "2024-01-01", "end": "2024-06-30" },
    "participants": ["张三", "李四", "我"]
  },
  "messages": [
    {
      "timestamp": "2024-01-15T14:30:22",
      "sender": "张三",
      "content": "消息内容",
      "type": "text|media|system|sticker|file",
      "reply_to": null
    }
  ]
}
```

`type` 分类：
- `text`：纯文本消息
- `media`：图片、视频、语音（标记为 `[图片]` 等）
- `system`：系统消息（加入、撤回、修改群名等）
- `sticker`：表情包/贴纸
- `file`：文件分享
