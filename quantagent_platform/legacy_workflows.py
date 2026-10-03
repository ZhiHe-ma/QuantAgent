"""Legacy Monitor/Daily sequencing over explicit public callbacks; no concrete IO."""
import json
from .legacy_ports import DailyPorts, MonitorPorts
from .daily_workflow import DAILY_SYSTEM_PROMPT, build_daily_prompt, render_daily_report

def run_monitor_pipeline(ports: MonitorPorts):
    """24小时常驻静默监控核心状态机"""
    print("🚀 [Monitor] 实时高精度快讯监听常驻进程已成功挂载底座。进入事件循环...")

    processed_ids = set(ports.read_json(ports.dedup_file, []))
    processed_fingerprints = set(ports.read_json(ports.fingerprint_file, []))
    failed_news_records = ports.read_json(ports.failed_news_file, {})
    if not isinstance(failed_news_records, dict):
        failed_news_records = {}

    sys_prompt_monitor = (
        "你是一个极端保守的微观量化因子标记器。请直接分析给定新闻对加密货币（主要是BTC与主流代币）价格的影响。\n"
        "评级纪律必须极硬：Low=普通观点/行情复盘/轻微产品动态；Medium=有方向但冲击路径间接；High=有清晰、直接、可交易的价格冲击路径；Critical=只允许非线性事件，例如交易所宕机、提现暂停、重大监管裁决、ETF突发批准或否决、巨额黑客攻击、大型钱包向交易所转移、宏观数据严重超预期。\n"
        "禁止把普通分析稿、行情直播、技术面评论、may/could/analyst 类文章评为 Critical。正常情况下 Critical 应极少出现。\n"
        "必须输出标准 JSON，严禁 Markdown、解释性文字、多余字段。格式如下：\n"
        '{"sentiment": "利多" | "利空" | "中性", "weight": "Critical" | "High" | "Medium" | "Low", "reason": "50字以内的极端精炼异动逻辑"}'
    )

    while True:
        try:
            flash_news_list = ports.fetch_crypto_flash_news()
            buffer_path = ports.get_buffer_path()
            day_buffers = ports.read_json(buffer_path, [])
            if not isinstance(day_buffers, list):
                day_buffers = []

            has_updates = False
            failure_state_changed = False

            candidates = []
            for news in flash_news_list:
                news_id = str(news.get("id", "")).strip()
                fingerprint = ports.news_fingerprint(news)
                if not news_id or news_id in processed_ids or fingerprint in processed_fingerprints:
                    continue
                candidates.append((news, news_id, fingerprint))

            if len(candidates) > ports.max_news_per_cycle:
                print(f" -> [控熵闸门] 本轮发现 {len(candidates)} 条增量，仅分析前 {ports.max_news_per_cycle} 条，防止成本与噪声失控。")

            for news, news_id, fingerprint in candidates[:ports.max_news_per_cycle]:
                title = ports.clamp_str(news.get("title", ""), 180)
                body = ports.clamp_str(news.get("body", ""), 800)
                print(f"🔥 捕获未处理原生增量快讯 [{news_id}]: {title}")

                news_payload = f"来源: {ports.clamp_str(news.get("source", "rss"), 40)}\n新闻标题: {title}\n新闻正文: {body}\n链接: {ports.clamp_str(news.get("url", ""), 240)}"
                ai_raw_decision = ""
                try:
                    ai_raw_decision = ports.request_deepseek(
                        news_payload,
                        use_r1=False,
                        system_prompt=sys_prompt_monitor,
                    )
                    decision_json = json.loads(ports.strip_json_fence(ai_raw_decision))
                    if not isinstance(decision_json, dict):
                        raise ValueError("decision is not dict")
                    if decision_json.get("sentiment") not in {"利多", "利空", "中性"}:
                        raise ValueError("invalid sentiment")
                    if decision_json.get("weight") not in {"Critical", "High", "Medium", "Low"}:
                        raise ValueError("invalid weight")
                    if not str(decision_json.get("reason", "")).strip():
                        raise ValueError("reason is empty")
                    factor_node = {
                        "id": news_id,
                        "fingerprint": fingerprint,
                        "time": ports.now().strftime("%H:%M:%S"),
                        "source": ports.clamp_str(news.get("source", "rss"), 40),
                        "published": ports.clamp_str(news.get("published", ""), 40),
                        "title": title,
                        "url": ports.clamp_str(news.get("url", ""), 240),
                        "sentiment": ports.clamp_str(decision_json.get("sentiment", "中性"), 12),
                        "weight": ports.clamp_str(decision_json.get("weight", "Low"), 12),
                        "reason": ports.clamp_str(decision_json.get("reason", "未提供有效定性依据"), 80)
                    }

                    original_weight = factor_node["weight"]
                    calibrated_weight, calibrate_reason = ports.calibrate_factor_weight(
                        title=title,
                        body=body,
                        weight=original_weight,
                        reason=factor_node.get("reason", "")
                    )
                    if calibrated_weight != original_weight:
                        factor_node["weight"] = calibrated_weight
                        factor_node["calibrated_from"] = original_weight
                        factor_node["calibration_reason"] = calibrate_reason
                        print(f" ╰─> [评级校准] {original_weight} -> {calibrated_weight} | {calibrate_reason}")

                    processed_ids.add(news_id)
                    processed_fingerprints.add(fingerprint)
                    if fingerprint in failed_news_records:
                        failed_news_records.pop(fingerprint, None)
                        failure_state_changed = True

                    if ports.weight_rank(factor_node["weight"]) >= ports.weight_rank(ports.min_store_weight):
                        day_buffers.append(factor_node)
                        day_buffers = ports.prune_day_buffer(day_buffers)
                        has_updates = True
                        print(f" ╰─> [因子入池] 定性: {factor_node['sentiment']} | 评级: {factor_node['weight']}")
                    else:
                        has_updates = True
                        print(f" ╰─> [低权重丢弃] 定性: {factor_node['sentiment']} | 评级: {factor_node['weight']}，不写入蓄水池。")
                except Exception as parse_err:
                    raw_preview = ports.clamp_str(locals().get("ai_raw_decision", ""), 240)
                    previous_failure = failed_news_records.get(fingerprint, {})
                    previous_attempts = (
                        previous_failure.get("attempts", 0)
                        if isinstance(previous_failure, dict)
                        else 0
                    )
                    attempts = previous_attempts + 1
                    failure_record = {
                        "id": news_id,
                        "fingerprint": fingerprint,
                        "source": ports.clamp_str(news.get("source", "rss"), 40),
                        "title": title,
                        "url": ports.clamp_str(news.get("url", ""), 240),
                        "attempts": attempts,
                        "last_failed_at": ports.now().isoformat(timespec="seconds"),
                        "error": ports.clamp_str(parse_err, 240),
                        "raw_preview": raw_preview,
                        "status": "retry_pending",
                    }

                    if attempts >= ports.max_news_ai_retries:
                        failure_record["status"] = "quarantined"
                        processed_ids.add(news_id)
                        processed_fingerprints.add(fingerprint)
                        has_updates = True
                        print(
                            f"🧯 因子提取连续失败 {attempts} 次，已进入隔离区并移出主队列: "
                            f"{news_id} | {parse_err}"
                        )
                    else:
                        print(
                            f"⚠️ 因子提取失败，第 {attempts}/{ports.max_news_ai_retries} 次；"
                            f"未写入已处理库，等待重试: {parse_err} | raw={raw_preview}"
                        )

                    failed_news_records[fingerprint] = failure_record
                    if len(failed_news_records) > 1000:
                        failed_news_records = dict(list(failed_news_records.items())[-1000:])
                    failure_state_changed = True

            if failure_state_changed:
                ports.write_json(ports.failed_news_file, failed_news_records)
            if has_updates:
                ports.write_json(buffer_path, day_buffers)
                ports.write_json(ports.dedup_file, list(processed_ids))
                ports.write_json(ports.fingerprint_file, list(processed_fingerprints)[-50000:])

        except Exception as loop_err:
            print(f"❌ 监听回路发生运行时异常，策略熔断器保护，3秒后自动软重启: {loop_err}")
            ports.sleep(3)

        ports.sleep(180)


def run_daily_pipeline(ports: DailyPorts):
    """每日 08:00 周期收敛宏观内参生成核心流水线"""
    started_at = ports.now().astimezone().isoformat(timespec="seconds")
    today_str = ports.now().strftime("%Y-%m-%d")
    print(f"🌅 [Daily] 启动清晨 08:00 周期收敛引擎，执行日期: {today_str}")

    raw_memory_state = ports.load_memory_state()
    today_report_path = ports.report_path(today_str)
    last_capsule_date = ports.clamp_str(
        (raw_memory_state.get("last_daily_capsule", {}) or {}).get("date", ""),
        20,
    )
    if (
        not ports.dry_run
        and not ports.force_daily_run
        and last_capsule_date == today_str
        and ports.report_exists(today_report_path)
    ):
        print(
            f"♻️ [Daily] {today_str} 已完成，幂等闸门跳过重复执行；"
            "未抓行情、未调用DeepSeek、未写文件、未推送企微。"
        )
        return {"status": "skipped", "date": today_str}
    if ports.force_daily_run and not ports.dry_run:
        print("⚠️ [Daily] FORCE_DAILY_RUN=true：显式绕过同日幂等闸门。")

    metrics = ports.fetch_market_signals()

    buffer_path = ports.get_buffer_path()
    filtered_news_context = []
    all_news = ports.read_json(buffer_path, [])
    if isinstance(all_news, list):
        from collections import Counter
        weight_counter = Counter(str(n.get("weight", "Low")) for n in all_news if isinstance(n, dict))
        print(f" -> 蓄水池评级分布: {dict(weight_counter)}")
        filtered_news_context = [n for n in all_news if n.get("weight") in ["Critical", "High"]]
        if not filtered_news_context:
            filtered_news_context = [n for n in all_news if n.get("weight") == "Medium"]
            if filtered_news_context:
                print(" -> 未发现 Critical/High，降级启用 Medium 因子作为今日背景噪声输入。")
    else:
        print("⚠️ 当日新闻蓄水池不是 list，已按空因子处理。")

    compact_news = ports.compact_news_factors(filtered_news_context)
    print(
        f" -> 已从蓄水池榨取高价值因子 {len(filtered_news_context)} 个；"
        f"经 Factor Gate 裁剪后进入推理层 {len(compact_news)} 个。"
    )

    memory_state = ports.clamp_memory_state(raw_memory_state)
    previous_memory = memory_state.get("last_daily_capsule", {})
    rolling_memory = memory_state.get("rolling_7d", [])

    macro_prompt = build_daily_prompt(
        previous_memory,
        rolling_memory,
        metrics,
        compact_news,
    )

    print("[Daily] 正在唤醒 DeepSeek-R1 深度推理链进行跨日因果审判...")
    ai_analysis = ports.request_deepseek(
        prompt=json.dumps(macro_prompt, ensure_ascii=False),
        use_r1=True,
        system_prompt=DAILY_SYSTEM_PROMPT,
    )

    obsidian_content = render_daily_report(
        report_date=today_str,
        metrics=metrics,
        previous_memory=previous_memory,
        news_factors=compact_news,
        raw_factor_count=len(filtered_news_context),
        analysis_text=ai_analysis,
    )
    if ports.dry_run:
        capsule = ports.generate_memory_capsule(today_str, ai_analysis, metrics, compact_news)
        audit_result = ports.record_signal_audit(
            today_str,
            started_at,
            capsule,
            metrics,
            compact_news,
            previous_memory,
            ai_analysis,
            {
                "report_written": False,
                "wecom_sent": False,
                "memory_saved": False,
            },
        )
        print("\n===== [DRY_RUN] 日报预览开始 =====")
        print(obsidian_content)
        print("===== [DRY_RUN] 日报预览结束 =====")
        print("\n===== [DRY_RUN] Memory Capsule 预览 =====")
        print(json.dumps(capsule, ensure_ascii=False, indent=2))
        print("🧪 [DRY_RUN] 验证完成：未写日报、未推送企微、未更新 Memory。")
        return {
            "report": obsidian_content,
            "capsule": capsule,
            "audit": audit_result,
        }

    file_path = today_report_path
    ports.write_report(file_path, obsidian_content)
    print(f"[Daily] 负熵内参已落盘至 Obsidian: {file_path}")

    wecom_sent = ports.push_to_wecom(
        f"### 📊 投研早餐内参 ({today_str})\n\n{ai_analysis}"
    )
    if wecom_sent:
        print("[Daily] 企微管道推送成功。")
    else:
        print("⚠️ [Daily] 企微管道未确认送达，审计账本将如实记录。")

    capsule = ports.generate_memory_capsule(today_str, ai_analysis, metrics, compact_news)
    memory_saved = ports.save_memory_capsule(capsule)
    audit_result = {"status": "skipped", "reason": "memory_not_saved"}
    if memory_saved:
        audit_result = ports.record_signal_audit(
            today_str,
            started_at,
            capsule,
            metrics,
            compact_news,
            previous_memory,
            ai_analysis,
            {
                "report_written": True,
                "wecom_sent": wecom_sent,
                "memory_saved": True,
            },
        )
    print("[Daily] 全链路收敛完成：今日判断已转化为明日记忆。")
    return {
        "report": obsidian_content,
        "capsule": capsule,
        "audit": audit_result,
    }


