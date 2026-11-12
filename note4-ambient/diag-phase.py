#!/usr/bin/env python3
import argparse
import re
from datetime import datetime
from pathlib import Path


def local_time(value):
    if value is None:
        return "无时间"
    return datetime.fromtimestamp(value).astimezone().isoformat(timespec="milliseconds")


def parse_play_end(line):
    if not line.startswith("ZECTRIX_PLAY_END"):
        return None
    reason = re.search(r"原始结束原因 ([0-9]+)", line)
    sent = re.search(r"已发送 ([0-9]+)/([0-9]+) 帧", line)
    duration = re.search(r"开始后 ([0-9]+(?:\.[0-9]+)?) 秒", line)
    if not reason or not sent or not duration:
        return None
    timestamp = re.search(r"本机时间 ([0-9]+(?:\.[0-9]+)?)", line)
    return {
        "reason": int(reason.group(1)),
        "sent": int(sent.group(1)),
        "total": int(sent.group(2)),
        "duration": float(duration.group(1)),
        "time": float(timestamp.group(1)) if timestamp else None,
    }


def parse_ping(path):
    samples = []
    if not path.exists():
        return samples
    for line in path.read_text(errors="replace").splitlines():
        timestamp = re.match(r"\[([0-9]+(?:\.[0-9]+)?)\]", line)
        if not timestamp:
            continue
        latency = re.search(r"\btime=([0-9]+(?:\.[0-9]+)?)\s*ms", line)
        sequence = re.search(r"\bicmp_seq=([0-9]+)", line)
        samples.append({
            "time": float(timestamp.group(1)),
            "latency": float(latency.group(1)) if latency else None,
            "sequence": int(sequence.group(1)) if sequence else None,
        })
    return samples


def show_ping_window(event, samples):
    if event["time"] is None:
        print("  失败前 ping：无时间，无法关联")
        return
    window = [sample for sample in samples if event["time"] - 10 <= sample["time"] <= event["time"]]
    if not window:
        print("  失败前 10 秒 ping：无样本")
        return
    print("  失败前 10 秒 ping（相对结果到达时间）：")
    for sample in window:
        latency = f"{sample['latency']:g} ms" if sample["latency"] is not None else "未应答"
        print(f"    {sample['time'] - event['time']:+8.3f} 秒 | {latency}")
    unanswered = sum(sample["latency"] is None for sample in window)
    missing = 0
    sequences = [sample["sequence"] for sample in window if sample["sequence"] is not None]
    for previous, current in zip(sequences, sequences[1:]):
        if current > previous + 1:
            missing += current - previous - 1
    print(f"  样本 {len(window)} · 未应答 {unanswered} · 序号缺口 {missing}")


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="分析 NOTE4 播放结束事件的周期相位及失败前 ping")
    parser.add_argument("--period", type=int, default=600, help="周期秒数，默认 600")
    parser.add_argument("--since", type=float, help="只统计不早于该 Unix 时间的记录")
    args = parser.parse_args()
    if args.period <= 0:
        parser.error("period 必须大于 0")

    events = []
    controlled = False
    for line in (root / "out/server.log").read_text(errors="replace").splitlines():
        if line.startswith("PLAY_BEGIN"):
            controlled = False
        elif line.startswith("ZECTRIX_DIAG_GAP_BEGIN"):
            controlled = True
        event = parse_play_end(line)
        if event is None:
            continue
        event["controlled"] = controlled
        if args.since is not None and (event["time"] is None or event["time"] < args.since):
            continue
        events.append(event)
    samples = parse_ping(root / "out/ping.log")

    print(f"周期：{args.period} 秒" + (f" · 起始：{local_time(args.since)}" if args.since is not None else ""))
    print("播放结束记录：")
    for event in events:
        phase = event["time"] % args.period if event["time"] is not None else None
        phase_text = f"{phase:.3f} 秒" if phase is not None else "无时间"
        mode = "受控断流" if event["controlled"] else "自然播放"
        print(
            f"{local_time(event['time'])} | 相位 {phase_text} | {mode} | 原因 {event['reason']} | "
            f"已发送 {event['sent']}/{event['total']} 帧 | 播放 {event['duration']:.2f} 秒"
        )
        if event["reason"] == 7:
            show_ping_window(event, samples)

    failures = [event for event in events if event["reason"] == 7 and event["time"] is not None and not event["controlled"]]
    controlled_failures = sum(event["reason"] == 7 and event["controlled"] for event in events)
    phases = [event["time"] % args.period for event in failures]
    max_difference = 0.0
    for index, phase in enumerate(phases):
        for other in phases[index + 1:]:
            difference = abs(phase - other)
            max_difference = max(max_difference, min(difference, args.period - difference))
    total = sum(event["duration"] for event in events)
    print("汇总：")
    print(f"  已结束播放累计 {total:.2f} 秒（{total / 60:.2f} 分钟），不含尚未结束的分段")
    print(f"  自然播放原因 7 共 {len(failures)} 次；受控断流原因 7 共 {controlled_failures} 次")
    print("  无时间记录不计入相位汇总")
    if failures:
        print("  失败相位：" + "、".join(f"{local_time(event['time'])} = {phase:.3f} 秒" for event, phase in zip(failures, phases)))
        print(f"  失败相位最大环形差值：{max_difference:.3f} 秒")
    else:
        print("  失败相位：无")


if __name__ == "__main__":
    main()
