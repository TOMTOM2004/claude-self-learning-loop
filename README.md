# claude-self-learning-loop

**Claude Code の自己学習型開発環境**

pytest のエラー解決時に「エラー内容・根本原因・解決策」をローカルベクトル DB に自動保存し、次回以降のセッションで自動検索・コンテキスト注入することで、Claude が過去の失敗から学習し続ける仕組みです。

## アーキテクチャ

```
【保存パス】
[pytest 失敗] → Claude が修正 → [pytest 成功]
                    ↓
      PostToolUse hook (pytest_tracker.py) が状態ファイルへ記録
                    ↓
      Stop hook (stop_lesson_check.py) が未保存エラーを検出しブロック
                    ↓
      Claude が lesson-recorder Skill を実行
      （ノイズフィルタ + 5 Whys RCA + 3文蒸留）
                    ↓
      mcp__memory__save_lesson → Ollama embedding → ChromaDB 保存

【取得パス】
User prompt → UserPromptSubmit hook (search_hook.py)
                    ↓
      ChromaDB を直接クエリ（低レイテンシ）
                    ↓
      関連教訓を systemMessage として Claude へ注入
```

## コンポーネント

| ファイル | 役割 |
|---|---|
| `claude-memory-mcp/server.py` | MCP stdio サーバー（save/search/list_lesson） |
| `claude-memory-mcp/search_hook.py` | UserPromptSubmit hook：意味検索して注入 |
| `claude-memory-mcp/stop_lesson_check.py` | Stop hook：未保存エラーを検出してブロック |
| `claude-memory-mcp/pytest_tracker.py` | PostToolUse(Bash) hook：pytest 結果を追跡 |
| `skills/lesson-recorder/SKILL.md` | Claude Code Skill（RCA + 蒸留フロー） |
| `claude-slack-approval/hook.py` | PreToolUse hook：Slack で承認/拒否 |
| `config/settings.json.example` | `~/.claude/settings.json` の設定テンプレート |

## セットアップ

### 1. 依存関係

```bash
cd ~/claude-memory-mcp
python3 -m venv .venv
.venv/bin/pip install mcp chromadb httpx
ollama pull nomic-embed-text
```

### 2. MCP サーバーの登録

`~/.claude/settings.json` の `mcpServers` に追加:

```json
{
  "mcpServers": {
    "memory": {
      "command": "/absolute/path/to/claude-memory-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/claude-memory-mcp/server.py"]
    }
  }
}
```

### 3. Hooks の設定

`config/settings.json.example` を参考に `~/.claude/settings.json` へ hooks を追加してください。
パスは自分の環境に合わせて書き換えてください。

### 4. Skill の配置

```bash
mkdir -p ~/.claude/skills/lesson-recorder
cp skills/lesson-recorder/SKILL.md ~/.claude/skills/lesson-recorder/
```

### 5. (オプション) Slack 承認 hook

```bash
cd claude-slack-approval
python3 -m venv .venv
.venv/bin/pip install slack-sdk python-dotenv
cp .env.example .env
# .env に SLACK_BOT_TOKEN と SLACK_CHANNEL_ID を設定
```

## 必要な環境

- [Claude Code](https://claude.ai/claude-code) CLI
- [Ollama](https://ollama.ai/) + `nomic-embed-text` モデル
- Python 3.11+

## 動作確認

```bash
# MCP サーバー単体テスト
echo '{"jsonrpc":"2.0","method":"tools/list","id":1}' | \
  ~/claude-memory-mcp/.venv/bin/python ~/claude-memory-mcp/server.py

# Claude Code で確認
# /mcp → memory サーバーと 3 ツールが表示される
# /lesson-recorder → テスト用教訓を手動保存できる
```

## ライセンス

MIT
