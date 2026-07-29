"""Collect the numbers that appear in the GitHub Stats block of the profile card.

Everything comes from the GraphQL API. Repository, star and follower counts are
cheap, but lines of code are not: they need the full commit history of every
repository, so those results are cached in cache/<sha256 of username>.txt and
only recomputed for repositories whose commit count has changed since last run.

Cache line format, one repository per line:

    <sha256 of owner/name> <total commits> <my commits> <additions> <deletions>
"""

import hashlib
import os
import time
from collections import Counter

import requests

API = "https://api.github.com/graphql"
CACHE_DIR = "cache"

# Anything owned, collaborated on, or reachable through an org counts towards
# "contributed to" and towards the lines-of-code total.
ALL_AFFILIATIONS = ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"]

USER_QUERY = """
query ($login: String!) {
  user(login: $login) {
    id
    createdAt
    followers { totalCount }
  }
}
"""

REPO_QUERY = """
query ($login: String!, $affiliations: [RepositoryAffiliation], $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, ownerAffiliations: $affiliations,
                 isFork: false) {
      totalCount
      nodes {
        nameWithOwner
        stargazerCount
        isPrivate
        primaryLanguage { name }
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
        defaultBranchRef { target { ... on Commit { history { totalCount } } } }
      }
      pageInfo { endCursor hasNextPage }
    }
  }
}
"""

CONTRIBUTIONS_QUERY = """
query ($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

HISTORY_QUERY = """
query ($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $cursor) {
            nodes {
              additions
              deletions
              author { user { id } }
            }
            pageInfo { endCursor hasNextPage }
          }
        }
      }
    }
  }
}
"""


class GitHubError(RuntimeError):
    pass


class GitHubStats:
    def __init__(self, username, token):
        self.username = username
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"bearer {token}"})
        self.queries = 0
        self.user_id = None

    # ------------------------------------------------------------------ api

    def query(self, document, **variables):
        """POST a query, retrying the transient failures this API is prone to.

        Large history queries regularly come back as 502s, and hammering them
        trips an undocumented abuse limit that answers 403. Both recover on
        their own given a little room.
        """
        delay = 2
        for attempt in range(5):
            self.queries += 1
            response = self.session.post(
                API, json={"query": document, "variables": variables}, timeout=60
            )
            if response.status_code == 200:
                payload = response.json()
                if "errors" in payload:
                    raise GitHubError(payload["errors"])
                return payload["data"]
            if response.status_code in (403, 429, 502, 503) and attempt < 4:
                time.sleep(delay)
                delay *= 2
                continue
            raise GitHubError(f"HTTP {response.status_code}: {response.text[:300]}")
        raise GitHubError("exhausted retries")

    # ---------------------------------------------------------------- basics

    def account(self):
        user = self.query(USER_QUERY, login=self.username)["user"]
        if user is None:
            raise GitHubError(f"no such user: {self.username}")
        self.user_id = user["id"]
        return {
            "created_at": user["createdAt"],
            "followers": user["followers"]["totalCount"],
        }

    def repositories(self, affiliations):
        """Every non-fork repository under the given affiliations."""
        nodes, cursor = [], None
        while True:
            page = self.query(
                REPO_QUERY, login=self.username,
                affiliations=affiliations, cursor=cursor,
            )["user"]["repositories"]
            nodes.extend(page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                return nodes
            cursor = page["pageInfo"]["endCursor"]

    def languages(self, repos, limit=6):
        """Most common primary language across the given repositories."""
        counts = Counter(
            repo["primaryLanguage"]["name"]
            for repo in repos
            if repo.get("primaryLanguage")
        )
        return [name for name, _ in counts.most_common(limit)]

    def language_bytes(self, repos, limit=6):
        """Share of source bytes per language, biggest first.

        Weighted by bytes rather than by repository count, so one enormous
        vendored directory does not read the same as one small hand-written
        project. GitHub supplies each language's brand colour.
        """
        totals, colours = Counter(), {}
        for repo in repos:
            for edge in (repo.get("languages") or {}).get("edges", []):
                name = edge["node"]["name"]
                totals[name] += edge["size"]
                colours[name] = edge["node"]["color"] or "#8b949e"

        overall = sum(totals.values())
        if not overall:
            return []
        return [
            {"name": name, "share": size / overall, "color": colours[name]}
            for name, size in totals.most_common(limit)
        ]

    def contributions(self, days=30):
        """Daily contribution counts for the last `days` days, plus the year total."""
        calendar = self.query(CONTRIBUTIONS_QUERY, login=self.username)[
            "user"]["contributionsCollection"]["contributionCalendar"]
        daily = [
            day["contributionCount"]
            for week in calendar["weeks"]
            for day in week["contributionDays"]
        ]
        return {"recent": daily[-days:], "year_total": calendar["totalContributions"]}

    # ------------------------------------------------------------------ loc

    def _repo_history(self, owner, name):
        """Additions, deletions and commit count attributable to this account."""
        additions = deletions = mine = 0
        cursor = None
        while True:
            branch = self.query(
                HISTORY_QUERY, owner=owner, name=name, cursor=cursor
            )["repository"]["defaultBranchRef"]
            if branch is None:  # empty repository, no default branch
                return 0, 0, 0
            history = branch["target"]["history"]
            for node in history["nodes"]:
                author = node["author"]["user"]
                if author and author["id"] == self.user_id:
                    mine += 1
                    additions += node["additions"]
                    deletions += node["deletions"]
            if not history["pageInfo"]["hasNextPage"]:
                return additions, deletions, mine
            cursor = history["pageInfo"]["endCursor"]

    def _cache_path(self):
        digest = hashlib.sha256(self.username.encode("utf-8")).hexdigest()
        return os.path.join(CACHE_DIR, f"{digest}.txt")

    def _read_cache(self):
        try:
            with open(self._cache_path(), encoding="utf-8") as handle:
                lines = [line.split() for line in handle if line.strip()]
        except FileNotFoundError:
            return {}
        return {
            parts[0]: tuple(int(value) for value in parts[1:5])
            for parts in lines if len(parts) >= 5
        }

    def _write_cache(self, entries):
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(self._cache_path(), "w", encoding="utf-8") as handle:
            for digest in sorted(entries):
                handle.write(f"{digest} {' '.join(str(v) for v in entries[digest])}\n")

    def lines_of_code(self, repos):
        """Total lines this account has added and removed across every repo.

        Repositories whose commit count is unchanged are read straight from the
        cache, so a normal daily run only walks the history of what actually
        moved.
        """
        cache = self._read_cache()
        entries, refreshed = {}, 0

        for repo in repos:
            branch = repo["defaultBranchRef"]
            commits = branch["target"]["history"]["totalCount"] if branch else 0
            digest = hashlib.sha256(
                repo["nameWithOwner"].encode("utf-8")
            ).hexdigest()

            cached = cache.get(digest)
            if cached and cached[0] == commits:
                entries[digest] = cached
                continue

            owner, name = repo["nameWithOwner"].split("/", 1)
            additions, deletions, mine = self._repo_history(owner, name)
            entries[digest] = (commits, mine, additions, deletions)
            refreshed += 1
            # Persist as we go: a mid-run failure on repository 80 of 95 should
            # not throw away the 79 histories already paid for.
            self._write_cache({**cache, **entries})

        self._write_cache(entries)

        additions = sum(entry[2] for entry in entries.values())
        deletions = sum(entry[3] for entry in entries.values())
        return {
            "added": additions,
            "deleted": deletions,
            "total": additions - deletions,
            "commits": sum(entry[1] for entry in entries.values()),
            "refreshed": refreshed,
        }

    # ---------------------------------------------------------------- public

    def collect(self):
        account = self.account()
        owned = self.repositories(["OWNER"])
        contributed = self.repositories(ALL_AFFILIATIONS)
        contributions = self.contributions()
        loc = self.lines_of_code(contributed)

        return {
            "created_at": account["created_at"],
            "followers": account["followers"],
            "repos": len(owned),
            "contributed": len(contributed),
            "stars": sum(repo["stargazerCount"] for repo in owned),
            "commits": loc["commits"],
            "loc_added": loc["added"],
            "loc_deleted": loc["deleted"],
            "loc_total": loc["total"],
            "languages": self.languages(contributed),
            "language_bytes": self.language_bytes(contributed),
            "contributions_recent": contributions["recent"],
            "contributions_year": contributions["year_total"],
            "repos_refreshed": loc["refreshed"],
            "api_calls": self.queries,
        }


def from_environment():
    token = os.environ.get("ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GitHubError("set ACCESS_TOKEN to a personal access token")
    username = os.environ.get("USER_NAME")
    if not username:
        raise GitHubError("set USER_NAME to your GitHub login")
    return GitHubStats(username, token)
