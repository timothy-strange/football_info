#!/usr/bin/env python3
"""Terminal UI for football-data.org fixtures."""

from __future__ import annotations

import curses
import json
import os
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


API_BASE = "https://api.football-data.org/v4"
TOKEN_ENV = "FOOTBALL_DATA_TOKEN"
TOKEN_FILE = Path.home() / ".config" / "football_info" / "token"

POPULAR_COMPETITIONS = [
    ("WC", "FIFA World Cup", "World"),
    ("PL", "Premier League", "England"),
    ("CL", "UEFA Champions League", "Europe"),
    ("BL1", "Bundesliga", "Germany"),
    ("PD", "Primera Division", "Spain"),
    ("SA", "Serie A", "Italy"),
    ("FL1", "Ligue 1", "France"),
    ("DED", "Eredivisie", "Netherlands"),
    ("PPL", "Primeira Liga", "Portugal"),
    ("MLS", "MLS", "United States"),
]


class FootballDataError(Exception):
    pass


class FootballDataClient:
    def __init__(self, token: str | None) -> None:
        self.token = token
        self.cache: dict[str, Any] = {}

    def get(self, path: str, params: dict[str, str] | None = None) -> Any:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"{API_BASE}{path}{query}"
        if url in self.cache:
            return self.cache[url]

        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        if self.token:
            request.add_header("X-Auth-Token", self.token)

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise FootballDataError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise FootballDataError(f"Network error: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise FootballDataError("API returned invalid JSON") from exc

        self.cache[url] = data
        return data


class App:
    def __init__(self, screen: Any) -> None:
        self.screen = screen
        self.client = FootballDataClient(load_token())
        self.show_scores = False
        self.selected_competition = "WC"
        self.selected_name = "FIFA World Cup"
        self.status = "Scores hidden. Press r on fixture screens to reveal temporarily."

    def run(self) -> None:
        curses.curs_set(0)
        curses.set_escdelay(25)
        self.screen.keypad(True)
        self.init_colors()
        while True:
            choice = self.menu(
                "Football Info",
                [
                    f"World Cup 2026 fixtures ({'scores shown' if self.show_scores else 'scores hidden'})",
                    f"Competition fixtures: {self.selected_name} ({self.selected_competition})",
                    "Select competition",
                    "Search team",
                    f"Toggle score visibility: {'shown' if self.show_scores else 'hidden'}",
                    "Quit",
                ],
            )
            if choice == 0:
                self.selected_competition = "WC"
                self.selected_name = "FIFA World Cup"
                self.show_fixtures("WC", "FIFA World Cup", {"season": "2026"})
            elif choice == 1:
                self.show_fixtures(self.selected_competition, self.selected_name, {})
            elif choice == 2:
                self.pick_competition()
            elif choice == 3:
                self.search_team()
            elif choice == 4:
                self.show_scores = not self.show_scores
                self.status = "Scores shown." if self.show_scores else "Scores hidden."
            else:
                return

    def pick_competition(self) -> None:
        options = [f"{code} - {name} ({area})" for code, name, area in POPULAR_COMPETITIONS]
        options.append("Fetch all available competitions")
        choice = self.menu("Select Competition", options)
        if choice < len(POPULAR_COMPETITIONS):
            code, name, _area = POPULAR_COMPETITIONS[choice]
            self.selected_competition = code
            self.selected_name = name
            self.status = f"Selected {name}."
            return

        try:
            data = self.client.get("/competitions")
            competitions = sorted(
                data.get("competitions", []),
                key=lambda c: (c.get("area", {}).get("name", ""), c.get("name", "")),
            )
        except FootballDataError as exc:
            self.message("Could not fetch competitions", str(exc))
            return

        if not competitions:
            self.message("No competitions", "API returned no competitions.")
            return

        labels = [self.competition_label(c) for c in competitions]
        selected = self.menu("Available Competitions", labels)
        comp = competitions[selected]
        self.selected_competition = str(comp.get("code") or comp.get("id"))
        self.selected_name = comp.get("name") or self.selected_competition
        self.status = f"Selected {self.selected_name}."

    def show_fixtures(self, code: str, name: str, params: dict[str, str]) -> None:
        try:
            data = self.client.get(f"/competitions/{code}/matches", params)
        except FootballDataError as exc:
            self.message("Could not fetch fixtures", str(exc))
            return
        matches = data.get("matches", [])
        title = f"{name} Fixtures"
        if params.get("season"):
            title += f" {params['season']}"
        self.match_list(title, matches)

    def search_team(self) -> None:
        query = self.prompt("Search team name")
        if not query:
            return
        scope = self.menu(
            "Search Scope",
            [
                f"Current competition: {self.selected_name}",
                "Popular competitions",
                "All available competitions",
            ],
        )

        competitions: list[tuple[str, str]] = []
        if scope == 0:
            competitions = [(self.selected_competition, self.selected_name)]
        elif scope == 1:
            competitions = [(code, name) for code, name, _area in POPULAR_COMPETITIONS]
        else:
            try:
                data = self.client.get("/competitions")
                competitions = [
                    (str(c.get("code") or c.get("id")), c.get("name") or str(c.get("code") or c.get("id")))
                    for c in data.get("competitions", [])
                    if c.get("code") or c.get("id")
                ]
            except FootballDataError as exc:
                self.message("Could not fetch competitions", str(exc))
                return

        matches: list[tuple[str, str, dict[str, Any]]] = []
        needle = query.casefold()
        for code, comp_name in competitions:
            try:
                data = self.client.get(f"/competitions/{code}/teams")
            except FootballDataError:
                continue
            for team in data.get("teams", []):
                names = [team.get("name", ""), team.get("shortName", ""), team.get("tla", "")]
                if any(needle in value.casefold() for value in names):
                    matches.append((code, comp_name, team))

        if not matches:
            self.message("No teams found", f"No team matched {query!r}.")
            return

        labels = [f"{team.get('name')} - {comp_name} ({code})" for code, comp_name, team in matches]
        selected = self.menu("Matching Teams", labels)
        code, comp_name, team = matches[selected]
        self.show_team_matches(code, comp_name, team)

    def show_team_matches(self, code: str, comp_name: str, team: dict[str, Any]) -> None:
        team_name = team.get("name", "Team")
        try:
            data = self.client.get(f"/competitions/{code}/matches")
        except FootballDataError as exc:
            self.message("Could not fetch fixtures", str(exc))
            return
        team_id = team.get("id")
        matches = [
            match
            for match in data.get("matches", [])
            if match.get("homeTeam", {}).get("id") == team_id or match.get("awayTeam", {}).get("id") == team_id
        ]
        self.match_list(f"{team_name} Fixtures - {comp_name}", matches)

    def match_list(self, title: str, matches: list[dict[str, Any]]) -> None:
        matches = sorted(matches, key=lambda match: match.get("utcDate") or "")
        reveal = self.show_scores
        rows = build_match_rows(matches)
        today_row = today_heading_row(rows)
        top = today_row if today_row is not None else 0
        today_match = match_index_from_row(rows, top) if today_row is not None else None
        index = today_match if today_match is not None else 0
        while True:
            height, width = self.screen.getmaxyx()
            visible = max(1, height - 5)
            rows = build_match_rows(matches)
            selected_row = match_row_index(rows, index)
            index = max(0, min(index, max(0, len(matches) - 1)))
            selected_row = match_row_index(rows, index)
            if selected_row < top:
                top = selected_row
            elif selected_row >= top + visible:
                top = selected_row - visible + 1

            self.clear_screen()
            self.draw_header(title, f"{len(matches)} matches | Enter details | r reveal/hide | b back")
            if not matches:
                self.add_wrapped(3, 2, "No fixtures returned.", width - 4)
            else:
                for row, item in enumerate(rows[top : top + visible], start=3):
                    kind, value = item
                    if kind == "heading":
                        self.add_line(row, 0, str(value)[: width - 1], self.header_attr())
                        continue
                    match_index = int(value)
                    selected = match_index == index
                    marker = "> " if selected else "  "
                    line = marker + self.match_summary(matches[match_index], reveal)
                    self.add_line(row, 0, line[: width - 1], self.selected_attr() if selected else self.normal_attr())
            self.draw_status(height - 1)
            key = self.screen.getch()
            if key in (ord("b"), ord("q"), 27):
                return
            if key in (curses.KEY_DOWN, ord("j")) and matches:
                index += 1
            elif key in (curses.KEY_UP, ord("k")) and matches:
                index -= 1
            elif key in (curses.KEY_NPAGE, ord(" ")) and matches:
                index += visible
            elif key == curses.KEY_PPAGE and matches:
                index -= visible
            elif key == ord("r"):
                reveal = not reveal
            elif key in (10, 13) and matches:
                self.match_details(matches[index], reveal)

    def match_details(self, match: dict[str, Any], reveal: bool) -> None:
        while True:
            height, width = self.screen.getmaxyx()
            home = match.get("homeTeam", {}).get("name") or "TBD"
            away = match.get("awayTeam", {}).get("name") or "TBD"
            lines = [
                f"{home} vs {away}",
                f"Kickoff: {format_date(match.get('utcDate'))}",
                f"Status: {match.get('status', 'UNKNOWN')}",
                f"Stage: {pretty(match.get('stage'))}",
                f"Group: {pretty(match.get('group'))}",
                f"Matchday: {match.get('matchday') or 'n/a'}",
                f"Venue: {match.get('venue') or 'n/a'}",
                f"Score: {format_score(match) if reveal else '[hidden]'}",
            ]
            self.clear_screen()
            self.draw_header("Match Details", "r reveal/hide | b back")
            row = 3
            for line in lines:
                row = self.add_wrapped(row, 2, line, width - 4) + 1
                if row >= height - 2:
                    break
            self.draw_status(height - 1)
            key = self.screen.getch()
            if key in (ord("b"), ord("q"), 27, 10, 13):
                return
            if key == ord("r"):
                reveal = not reveal

    def menu(self, title: str, options: list[str]) -> int:
        index = 0
        top = 0
        while True:
            height, width = self.screen.getmaxyx()
            visible = max(1, height - 5)
            index = max(0, min(index, len(options) - 1))
            if index < top:
                top = index
            elif index >= top + visible:
                top = index - visible + 1

            self.clear_screen()
            self.draw_header(title, "Up/down select | Enter choose | q quit/back")
            for row, option in enumerate(options[top : top + visible], start=3):
                selected = top + row - 3 == index
                self.add_line(
                    row,
                    0,
                    ("> " if selected else "  ") + option[: width - 3],
                    self.selected_attr() if selected else self.normal_attr(),
                )
            self.draw_status(height - 1)
            key = self.screen.getch()
            if key in (curses.KEY_DOWN, ord("j")):
                index += 1
            elif key in (curses.KEY_UP, ord("k")):
                index -= 1
            elif key in (curses.KEY_NPAGE, ord(" ")):
                index += visible
            elif key == curses.KEY_PPAGE:
                index -= visible
            elif key in (10, 13):
                return index
            elif key in (ord("q"), 27):
                return len(options) - 1

    def prompt(self, label: str) -> str:
        curses.curs_set(1)
        height, width = self.screen.getmaxyx()
        self.clear_screen()
        self.draw_header(label, "Enter text | Esc cancel")
        curses.echo()
        self.screen.addstr(3, 2, "> ")
        self.screen.refresh()
        try:
            value = self.screen.getstr(3, 4, max(1, width - 6)).decode("utf-8", "replace").strip()
        except KeyboardInterrupt:
            value = ""
        curses.noecho()
        curses.curs_set(0)
        _ = height
        return value

    def message(self, title: str, body: str) -> None:
        while True:
            height, width = self.screen.getmaxyx()
            self.clear_screen()
            self.draw_header(title, "Press any key")
            self.add_wrapped(3, 2, body, width - 4)
            self.draw_status(height - 1)
            self.screen.getch()
            return

    def competition_label(self, comp: dict[str, Any]) -> str:
        area = comp.get("area", {}).get("name", "Unknown")
        code = comp.get("code") or comp.get("id")
        return f"{code} - {comp.get('name', 'Unknown')} ({area})"

    def match_summary(self, match: dict[str, Any], reveal: bool) -> str:
        time = format_time(match.get("utcDate"))
        home = match.get("homeTeam", {}).get("shortName") or match.get("homeTeam", {}).get("name") or "TBD"
        away = match.get("awayTeam", {}).get("shortName") or match.get("awayTeam", {}).get("name") or "TBD"
        score = format_score(match) if reveal else "[hidden]"
        status = match.get("status", "")
        group = pretty(match.get("group"))
        extra = f" | {group}" if group != "n/a" else ""
        return f"{time} | {home} vs {away} | {score} | {status}{extra}"

    def draw_header(self, title: str, help_text: str) -> None:
        width = self.screen.getmaxyx()[1]
        token = "token ok" if self.client.token else f"set {TOKEN_ENV} or {TOKEN_FILE}"
        self.add_line(0, 0, title[: width - 1], self.header_attr())
        self.add_line(1, 0, f"{help_text} | {token}"[: width - 1], self.muted_attr())
        self.add_line(2, 0, "-" * max(0, width - 1), self.muted_attr())

    def draw_status(self, row: int) -> None:
        width = self.screen.getmaxyx()[1]
        self.add_line(row, 0, self.status[: width - 1], self.muted_attr())
        self.screen.refresh()

    def init_colors(self) -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        if hasattr(curses, "assume_default_colors"):
            curses.assume_default_colors(curses.COLOR_BLACK, curses.COLOR_WHITE)
        else:
            curses.use_default_colors()
        background = 15 if curses.COLORS >= 16 else curses.COLOR_WHITE
        highlight = 11 if curses.COLORS >= 16 else curses.COLOR_YELLOW
        if curses.can_change_color() and curses.COLORS >= 16:
            curses.init_color(background, 1000, 1000, 1000)
            curses.init_color(highlight, 1000, 1000, 700)
        curses.init_pair(1, curses.COLOR_BLACK, background)
        curses.init_pair(2, curses.COLOR_BLUE, background)
        curses.init_pair(3, curses.COLOR_BLACK, highlight)
        curses.init_pair(4, curses.COLOR_BLACK, background)
        self.screen.bkgd(" ", curses.color_pair(1))
        self.screen.clear()

    def clear_screen(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        blank = " " * max(0, width - 1)
        attr = self.normal_attr()
        for row in range(height):
            self.add_line(row, 0, blank, attr)

    def normal_attr(self) -> int:
        return curses.color_pair(1) if curses.has_colors() else 0

    def header_attr(self) -> int:
        return (curses.color_pair(2) if curses.has_colors() else 0) | curses.A_BOLD

    def selected_attr(self) -> int:
        return curses.color_pair(3) | curses.A_BOLD if curses.has_colors() else curses.A_REVERSE

    def muted_attr(self) -> int:
        return curses.color_pair(4) if curses.has_colors() else 0

    def add_line(self, row: int, col: int, text: str, attr: int = 0) -> None:
        try:
            self.screen.addstr(row, col, text, attr)
        except curses.error:
            pass

    def add_wrapped(self, row: int, col: int, text: str, width: int) -> int:
        for line in textwrap.wrap(text, width=width) or [""]:
            self.add_line(row, col, line)
            row += 1
        return row


def format_date(value: str | None) -> str:
    local = parse_local_datetime(value)
    if local is None:
        return "TBD" if not value else value
    return local.strftime("%Y-%m-%d %H:%M")


def format_time(value: str | None) -> str:
    local = parse_local_datetime(value)
    if local is None:
        return "TBD"
    return local.strftime("%H:%M")


def format_day_heading(value: str | None) -> str:
    local = parse_local_datetime(value)
    if local is None:
        return "TBD"
    heading = local.strftime("%A %Y-%m-%d")
    if local.date() == datetime.now().astimezone().date():
        heading += " *** TODAY ***"
    return heading


def parse_local_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone()


def build_match_rows(matches: list[dict[str, Any]]) -> list[tuple[str, str | int]]:
    rows: list[tuple[str, str | int]] = []
    current_heading = None
    for match_index, match in enumerate(matches):
        heading = format_day_heading(match.get("utcDate"))
        if heading != current_heading:
            rows.append(("heading", heading))
            current_heading = heading
        rows.append(("match", match_index))
    return rows


def match_row_index(rows: list[tuple[str, str | int]], match_index: int) -> int:
    for row_index, (kind, value) in enumerate(rows):
        if kind == "match" and value == match_index:
            return row_index
    return 0


def today_heading_row(rows: list[tuple[str, str | int]]) -> int | None:
    for row_index, (kind, value) in enumerate(rows):
        if kind == "heading" and "*** TODAY ***" in str(value):
            return row_index
    return None


def match_index_from_row(rows: list[tuple[str, str | int]], row: int) -> int | None:
    for kind, value in rows[row:]:
        if kind == "match":
            return int(value)
    return None


def format_score(match: dict[str, Any]) -> str:
    score = match.get("score", {}).get("fullTime", {})
    home = score.get("home")
    away = score.get("away")
    if home is None or away is None:
        return "-"
    return f"{home}-{away}"


def pretty(value: Any) -> str:
    if not value:
        return "n/a"
    return str(value).replace("_", " ").title()


def load_token() -> str | None:
    env_token = os.environ.get(TOKEN_ENV)
    if env_token:
        return env_token.strip()
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def main() -> None:
    curses.wrapper(lambda screen: App(screen).run())


if __name__ == "__main__":
    main()
