# 知识星球股票舆情分析器

自动爬取多个知识星球内容，利用 AI 深度分析财经情绪倾向，生成 Excel 报告。

## 功能

- 🔐 Cookie 管理 + 扫码登录（Playwright 无头浏览器）
- 🕷️ 限流爬虫（20次/分钟，指数退避重试）
- 🤖 AI 深度财经分析（Moonshot/Claude/OpenAI，关键词预过滤）
- 📊 Excel 报告（按星球分页签，群主观点高权重标注）
- 📢 企业微信通知（二维码推送、结果通知、异常告警）
- 🔄 多星球支持 + 增量爬取

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```bash
# 知识星球（多个用逗号分隔）
ZSXQ_GROUP_ID=28888221524121,15552521555222

# AI API（Moonshot）
OPENAI_API_KEY=sk-xxx
OPENAI_API_BASE=https://api.moonshot.cn/v1

# 可选：企业微信机器人
WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
```

### 3. 运行

```bash
# 爬取+分析一条龙
python main.py run --start-date 2026-02-14

# 增量爬取+分析（自动从上次位置继续）
python main.py run

# 只爬取数据
python main.py fetch --start-date 2026-02-14

# 只分析已有数据
python main.py analyze --data data/topics_2026-02-19.json
```

首次运行会触发扫码登录，二维码通过企业微信推送（或保存到 `data/qrcode.png`）。

## 项目结构

```
zsxq-sentiment/
├── src/
│   ├── __init__.py      # 包初始化
│   ├── auth.py          # 认证模块（Cookie + 扫码登录）
│   ├── crawler.py       # 爬虫模块（限流 + 重试 + 增量）
│   ├── analyzer.py      # AI深度财经分析（预过滤 + 群主识别）
│   ├── report.py        # Excel报告（多星球分页签）
│   ├── notify.py        # 企业微信通知
│   └── config.py        # 配置管理
├── data/
│   ├── cookie.json      # Cookie存储（自动生成）
│   ├── last_fetch.json  # 各星球最后爬取时间（自动生成）
│   └── topics_*.json    # 爬取的原始数据
├── output/              # Excel报告输出
├── logs/                # 运行日志
├── .env                 # 环境变量（不入库）
├── .env.example         # 环境变量模板
├── requirements.txt     # Python依赖
├── main.py              # 入口
└── README.md
```

## AI 分析要点

每条帖子（含评论）整体发送给大模型，分析内容包括：

- 是否涉及股票、期货、区块链等财经话题
- 金融产品类型和具体标的
- 整体多空看法及原因
- 群主观点单独提取（权重更高）

## Excel 报告结构

多星球时按星球名称分页签，每个星球包含：

- **财经分析页签**：仅财经相关帖子，含群主看法、原因分析等
- **全部帖子页签**：所有帖子概览

每个页签：
- 第一行：星球名称 + Group ID
- 第二行：字段名称
- 第三行起：数据

## 高可用设计

| 场景 | 策略 |
|------|------|
| HTTP请求失败 | 3次重试，指数退避 |
| AI API失败 | 5次重试，10s起指数退避 |
| Claude不可用 | 降级到OpenAI |
| Excel生成失败 | 降级为CSV |
| Cookie过期 | 自动触发扫码登录 |
| 非财经帖子 | 关键词预过滤，跳过AI调用 |

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| ZSXQ_GROUP_ID | ✅ | 知识星球群组ID（多个逗号分隔） |
| OPENAI_API_KEY | ✅ | AI API密钥 |
| OPENAI_API_BASE | ❌ | 自定义API地址（默认OpenAI官方） |
| ANTHROPIC_API_KEY | ❌ | Claude API密钥（备选） |
| WECOM_WEBHOOK | ❌ | 企业微信机器人webhook |
| ZSXQ_GROUP_OWNER_ID | ❌ | 群主user_id（用于标注群主观点） |

## 免责声明

⚠️ 本工具仅供个人学习研究使用，请遵守知识星球用户协议，不得用于商业用途。
