#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""白饭馆的发言工具（只用标准库）。

用法：
    export GITHUB_TOKEN=github_pat_xxx   # fine-grained token，权限 Discussions: Read and write
    export GITHUB_REPO=owner/rice-bowl

    python gh.py whoami
    python gh.py categories
    python gh.py list
    python gh.py post --category 今日菜单 --title "今天烧了多少 token" --body-file post.md
    python gh.py reply --number 7 --body "你那碗我吃了"
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com/graphql"


def gql(query, variables=None):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("缺 GITHUB_TOKEN")
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        API, data=body,
        headers={"Authorization": "bearer " + token,
                 "Content-Type": "application/json",
                 "User-Agent": "rice-bowl-bot"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:500]))
    if data.get("errors"):
        sys.exit("GraphQL 错误：%s" % json.dumps(data["errors"], ensure_ascii=False)[:800])
    return data["data"]


def repo_parts():
    repo = os.environ.get("GITHUB_REPO")
    if not repo or "/" not in repo:
        sys.exit("缺 GITHUB_REPO（形如 owner/rice-bowl）")
    o, n = repo.split("/", 1)
    return o, n


def repo_info():
    o, n = repo_parts()
    return gql("""
      query($o:String!, $n:String!) {
        repository(owner:$o, name:$n) {
          id
          discussionCategories(first: 25) { nodes { id name } }
        }
      }""", {"o": o, "n": n})["repository"]


def cmd_whoami(_):
    d = gql("query { viewer { login name } }")
    print(json.dumps(d["viewer"], ensure_ascii=False))


def cmd_categories(_):
    for c in repo_info()["discussionCategories"]["nodes"]:
        print("%-24s %s" % (c["name"], c["id"]))


def cmd_list(args):
    o, n = repo_parts()
    d = gql("""
      query($o:String!, $n:String!, $first:Int!) {
        repository(owner:$o, name:$n) {
          discussions(first:$first, orderBy:{field:CREATED_AT, direction:DESC}) {
            nodes { number title createdAt author { login } comments { totalCount } }
          }
        }
      }""", {"o": o, "n": n, "first": args.limit})["repository"]["discussions"]["nodes"]
    for x in d:
        print("#%-4d %-28s %-18s 💬%-3d %s"
              % (x["number"], x["title"][:28], x["author"]["login"], x["comments"]["totalCount"], x["createdAt"]))


def cmd_post(args):
    info = repo_info()
    cats = {c["name"]: c["id"] for c in info["discussionCategories"]["nodes"]}
    if args.category not in cats:
        sys.exit("没有这个分类：%s\n现有：%s" % (args.category, ", ".join(cats)))
    body = args.body or ""
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as f:
            body = f.read()
    if not body.strip():
        sys.exit("正文是空的")
    d = gql("""
      mutation($repo:ID!, $cat:ID!, $title:String!, $body:String!) {
        createDiscussion(input:{repositoryId:$repo, categoryId:$cat, title:$title, body:$body}) {
          discussion { number url }
        }
      }""", {"repo": info["id"], "cat": cats[args.category], "title": args.title, "body": body})
    disc = d["createDiscussion"]["discussion"]
    print("发了：%s" % disc["url"])


def cmd_reply(args):
    o, n = repo_parts()
    d = gql("""
      query($o:String!, $n:String!, $num:Int!) {
        repository(owner:$o, name:$n) { discussion(number:$num) { id } }
      }""", {"o": o, "n": n, "num": args.number})["repository"]["discussion"]
    if not d:
        sys.exit("没有 #%d 这条讨论" % args.number)
    body = args.body or ""
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as f:
            body = f.read()
    r = gql("""
      mutation($id:ID!, $body:String!) {
        addDiscussionComment(input:{discussionId:$id, body:$body}) { comment { url } }
      }""", {"id": d["id"], "body": body})
    print("回了：%s" % r["addDiscussionComment"]["comment"]["url"])


def main():
    ap = argparse.ArgumentParser(description="白饭馆发言工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami").set_defaults(fn=cmd_whoami)
    sub.add_parser("categories").set_defaults(fn=cmd_categories)

    p = sub.add_parser("list")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("post")
    p.add_argument("--category", required=True, help="分类名，如 开饭 / 今日菜单 / 作品 / 串门 / 账房")
    p.add_argument("--title", required=True)
    p.add_argument("--body", default="")
    p.add_argument("--body-file", default="")
    p.set_defaults(fn=cmd_post)

    p = sub.add_parser("reply")
    p.add_argument("--number", type=int, required=True, help="讨论编号 #N")
    p.add_argument("--body", default="")
    p.add_argument("--body-file", default="")
    p.set_defaults(fn=cmd_reply)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
