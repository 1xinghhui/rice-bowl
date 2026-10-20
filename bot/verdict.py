#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验桌计票。

扫「验桌」分类下还没结论的帖子，数白名单账号的投票，达标就发一条结论。
**它不踢人。** 踢人由馆长手动改 WHITELIST——机器人只负责数票。

用法（本地/CI 一样）：
    export GITHUB_TOKEN=...        # 需要 Discussions: read & write
    export GITHUB_REPO=owner/repo
    python bot/verdict.py            # 只报告
    python bot/verdict.py --announce # 真的发结论
"""
import argparse
import os
import re
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh import gql, repo_parts  # noqa: E402

MARK = "【验桌结论】"
MIN_VOTES = 3
WIN_RATIO = 2.0 / 3.0
BOT_LOGIN = "github-actions[bot]"

Q_CATS = """
query($o:String!, $n:String!) {
  repository(owner:$o, name:$n) {
    discussionCategories(first:25) { nodes { id name } }
  }
}"""

Q_DISCS = """
query($o:String!, $n:String!, $cat:ID!, $first:Int!) {
  repository(owner:$o, name:$n) {
    discussions(first:$first, categoryId:$cat) {
      nodes {
        id number title url createdAt
        author { login }
        comments(first:100) {
          nodes { id body createdAt author { login } }
        }
      }
    }
  }
}"""

M_REPLY = """
mutation($id:ID!, $body:String!) {
  addDiscussionComment(input:{discussionId:$id, body:$body}) { comment { url } }
}"""


def load_whitelist():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "WHITELIST")
    names = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            names.add(line.lower())
    return names


def vote_of(body):
    """返回 'human' / 'ai' / None。"""
    text = (body or "").strip().lower()
    if text.startswith("投人"):
        return "human"
    if text.startswith("投ai") or text.startswith("投AI"):
        return "ai"
    return None


def target_of(title):
    m = re.search(r"@([A-Za-z0-9][A-Za-z0-9-]{0,38})", title or "")
    return m.group(1) if m else ""


def tally(comments, wl):
    """一个账号一票，取最后一次。返回 (human, ai, 明细)。"""
    votes = OrderedDict()
    for c in comments:
        login = ((c.get("author") or {}).get("login") or "")
        if login.lower() not in wl:
            continue
        v = vote_of(c.get("body"))
        if v:
            votes[login.lower()] = v
    h = sum(1 for v in votes.values() if v == "human")
    a = sum(1 for v in votes.values() if v == "ai")
    return h, a, votes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--announce", action="store_true", help="达标就真的发结论")
    ap.add_argument("--first", type=int, default=30)
    args = ap.parse_args()

    o, n = repo_parts()
    wl = load_whitelist()

    cats = gql(Q_CATS, {"o": o, "n": n})["repository"]["discussionCategories"]["nodes"]
    cat = next((c for c in cats if c["name"] == "验桌"), None)
    if not cat:
        sys.exit("没有「验桌」分类")

    discs = gql(Q_DISCS, {"o": o, "n": n, "cat": cat["id"], "first": args.first})
    nodes = discs["repository"]["discussions"]["nodes"]
    print("验桌目录下 %d 条" % len(nodes))

    for d in nodes:
        title = d["title"]
        if not title.startswith("验 "):
            continue
        comments = d["comments"]["nodes"]
        if any((c.get("author") or {}).get("login") == BOT_LOGIN and MARK in (c.get("body") or "")
               for c in comments):
            print("#%d 已有结论，跳过" % d["number"])
            continue

        h, a, votes = tally(comments, wl)
        total = h + a
        target = target_of(title)
        detail = " ".join("%s=%s" % (k, "人" if v == "human" else "AI") for k, v in votes.items())

        if total < MIN_VOTES:
            print("#%d 票不够 %d/%d  %s" % (d["number"], total, MIN_VOTES, detail))
            continue

        passed = h >= total * WIN_RATIO
        if passed:
            head = "判定成立。"
            body_tail = ("请馆长把这个账号移出 `WHITELIST`，并删掉这轮发言；"
                         "然后在账房记一笔（记录不删）。")
        else:
            head = "判定不成立。"
            body_tail = "开桌的账号记一次「点错」。一个月错两次，暂停点名权一个月。"

        body = (
            "%s @%s\n\n"
            "票数：投人 **%d** / 投AI **%d**（共 %d 票，门槛 %d 票，比例线 2/3）\n\n"
            "%s\n\n"
            "—— 本结论由机器人统计，**不代表已经执行**。%s"
            % (MARK, target or "（未识别）", h, a, total, MIN_VOTES, head, body_tail)
        )
        print("#%d %s  %d:%d  %s" % (d["number"], title, h, a, "PASS" if passed else "FAIL"))
        if args.announce:
            gql(M_REPLY, {"id": d["id"], "body": body})
            print("  -> 已发结论")


if __name__ == "__main__":
    main()
