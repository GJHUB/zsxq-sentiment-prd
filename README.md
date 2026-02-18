# 知识星球股票舆情分析器

自动爬取知识星球内容，利用 AI 分析股票情绪倾向，生成 Excel 报告。

## 功能

- 🔐 Cookie 管理 + 扫码登录（Playwright 无头浏览器）
- 🕷️ 限流爬虫（20次/分钟，指数退避重试）
- 🤖 AI 情绪分析（Claude/OpenAI，批量处理+降级）
- 📊 Excel 报告（股票汇总 + 评论明细，条件着色）
- 📢 企业微信通知（二维码推送、结果通知、异常告警）

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入实际配置
```

### 3. 运行

```bash
python main.py
```

### 4. 定时任务（可选）

```bash
# 每天18:00运行
0 18 * * * cd /path/to/zsxq-sentiment && python main.py >> logs/cron.log 2>&1
```

## 项目结构

```
zsxq-sentiment/
├── src/
│   ├── __init__.py      # 包初始化
│   ├── auth.py          # 认证模块（Cookie + 扫码）
│   ├── crawler.py       # 爬虫模块（限流 + 重试）
│   ├── analyzer.py      # AI分析（批量 + 降级）
│   ├── report.py        # Excel报告生成
│   ├── notify.py        # 企业微信通知
│   └── config.py        # 配置管理
├── data/                # Cookie存储
├── output/              # Excel输出
├── logs/                # 运行日志
├── .env.example         # 环境变量模板
├── requirements.txt     # Python依赖
├── main.py              # 入口
└── README.md
```

## 高可用设计

| 场景 | 策略 |
|------|------|
| HTTP请求失败 | 3次重试，指数退避 1→2→4s |
| AI API失败 | Claude → OpenAI 降级 |
| 批量分析失败 | 降级为单条处理 |
| Excel生成失败 | 降级为CSV |
| Cookie过期 | 自动触发扫码登录 |

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| ZSXQ_GROUP_ID | ✅ | 知识星球群组ID |
| ANTHROPIC_API_KEY | 二选一 | Claude API密钥 |
| OPENAI_API_KEY | 二选一 | OpenAI API密钥 |
| WECOM_WEBHOOK | ❌ | 企业微信机器人webhook |

## 免责声明

⚠️ 本工具仅供个人学习研究使用，请遵守知识星球用户协议，不得用于商业用途。
