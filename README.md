# football_info

Terminal UI for football-data.org fixtures.

## Setup

Create an API token at <https://www.football-data.org/client/register>, then export it:

```sh
export FOOTBALL_DATA_TOKEN=your_token_here
```

or save it locally:

```sh
mkdir -p ~/.config/football_info
chmod 700 ~/.config/football_info
printf '%s\n' 'your_token_here' > ~/.config/football_info/token
chmod 600 ~/.config/football_info/token
```

`FOOTBALL_DATA_TOKEN` takes precedence over `~/.config/football_info/token`.

## Run

```sh
./football_info.py
```

or:

```sh
python3 football_info.py
```

## Features

- Menu-based terminal UI.
- World Cup 2026 fixtures shortcut using competition `WC` and `season=2026`.
- Select from popular competitions or fetch all available competitions.
- Team search scoped to current, popular, or all competitions.
- Scores hidden by default to avoid spoilers; press `r` on fixture screens to reveal temporarily.

## Notes

football-data.org access varies by token plan. If an endpoint fails, the app shows the API error rather than hiding it.
